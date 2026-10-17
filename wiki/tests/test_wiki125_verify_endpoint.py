"""WIKI-125: page verify endpoint (PATCH /pages/{pk}/verify/).

Covers the WIKI-123 S-B contract:
- permission matrix: viewer denied, editor ok, admin ok, cross-org denied (404),
  same-org non-member denied (404 — visibility scoping)
- owner defaulting: first verify defaults the owner to the verifier;
  re-verify preserves it unless an explicit owner is passed
- idempotent re-verify: a second verify just refreshes verified_at/verified_by
- conflict safety: a concurrent content write between the verify's read and
  its transaction wins — the endpoint returns 409 and never attests content
  the verifier did not see (verify never resurrects a cleared state)
"""
from unittest import mock

from django.db.models.signals import post_save
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from wiki.authentication import FederatedUser
from wiki.models import Page, Space, SpaceMembership
from wiki.signals import update_search_vector

ORG_A = 1
ORG_B = 2


def _fed(user_id, org, role='member'):
    """Federated (JWT-derived) user — the prod request.user shape."""
    return FederatedUser(
        user_id=user_id,
        email=f'user{user_id}@org{org}.example',
        username=f'user{user_id}',
        is_staff=False,
        is_superuser=False,
        enabled_services=['wiki'],
        organization_memberships={org: role},
    )


def _client(user, org):
    c = APIClient(HTTP_X_ORGANIZATION_ID=str(org))
    c.force_authenticate(user=user)
    return c


class VerifyEndpointTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.editor = _fed(301, ORG_A, role='member')   # becomes space editor
        self.admin = _fed(302, ORG_A, role='admin')
        self.viewer = _fed(303, ORG_A, role='member')   # becomes space viewer
        self.nonmember = _fed(304, ORG_A, role='member')
        self.outsider = _fed(401, ORG_B, role='admin')

        self.c_editor = _client(self.editor, ORG_A)
        self.c_admin = _client(self.admin, ORG_A)
        self.c_viewer = _client(self.viewer, ORG_A)
        self.c_nonmember = _client(self.nonmember, ORG_A)
        self.c_outsider = _client(self.outsider, ORG_B)

        self.space = Space.objects.create(
            organization_id=ORG_A, key='VRF', name='Verify Tests',
            visibility='private', owner_id=self.admin.id,
        )
        SpaceMembership.objects.create(space=self.space, user_id=self.editor.id, role='editor')
        SpaceMembership.objects.create(space=self.space, user_id=self.viewer.id, role='viewer')

        self.page = Page.objects.create(
            space=self.space, title='Verified runbook',
            content_text='# H1\n\nbody', content_json={},
            created_by_id=self.editor.id,
        )
        self.url = f'/api/pages/{self.page.pk}/verify/'
        self.page_url = f'/api/pages/{self.page.pk}/'

    # ---- permission matrix -------------------------------------------------

    def test_editor_can_verify(self):
        resp = self.c_editor.patch(self.url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.data['verified_by_id'], self.editor.id)
        self.assertEqual(resp.data['verify_owner_id'], self.editor.id)

    def test_admin_can_verify(self):
        resp = self.c_admin.patch(self.url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.data['verified_by_id'], self.admin.id)

    def test_viewer_denied(self):
        resp = self.c_viewer.patch(self.url, {}, format='json')
        self.assertIn(resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.page.refresh_from_db()
        self.assertIsNone(self.page.verified_at)

    def test_same_org_nonmember_denied(self):
        resp = self.c_nonmember.patch(self.url, {}, format='json')
        self.assertIn(resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_cross_org_denied(self):
        resp = self.c_outsider.patch(self.url, {}, format='json')
        self.assertIn(resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.page.refresh_from_db()
        self.assertIsNone(self.page.verified_at)

    # ---- owner defaulting + idempotence ------------------------------------

    def test_reverify_preserves_owner(self):
        self.c_editor.patch(self.url, {}, format='json')
        resp = self.c_admin.patch(self.url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # first verifier's ownership survives the re-verify
        self.assertEqual(resp.data['verify_owner_id'], self.editor.id)
        self.assertEqual(resp.data['verified_by_id'], self.admin.id)

    def test_explicit_owner_overrides(self):
        resp = self.c_editor.patch(self.url, {'owner': self.admin.id}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['verify_owner_id'], self.admin.id)
        self.assertEqual(resp.data['verified_by_id'], self.editor.id)

    def test_explicit_owner_as_digit_string(self):
        resp = self.c_editor.patch(self.url, {'owner': str(self.admin.id)}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['verify_owner_id'], self.admin.id)

    def test_invalid_owner_type_rejected(self):
        resp = self.c_editor.patch(self.url, {'owner': 'not-a-user'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.page.refresh_from_db()
        self.assertIsNone(self.page.verified_at)

    def test_reverify_updates_timestamp(self):
        r1 = self.c_editor.patch(self.url, {}, format='json')
        first_at = r1.data['verified_at']
        r2 = self.c_editor.patch(self.url, {}, format='json')
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r2.data['verified_at'], first_at)

    # ---- conflict safety (S-B: verify never resurrects a cleared state) -----

    def test_concurrent_content_write_wins(self):
        """A content write landing between the verifier's read and the verify's
        transaction must win: 409, no verification, and the cleared state stays
        cleared."""
        real_sfu = Page.objects.select_for_update

        with mock.patch('wiki.views.Page.objects.select_for_update') as sfu:
            # Simulate the content write committing after get_object()'s read
            # but before the verify transaction locks the row.
            def _race(*args, **kwargs):
                # first call inside verify(): mutate content like a concurrent write
                self.page.refresh_from_db()
                self.page.content_text = '# H1\n\nbody REWRITTEN BY CONCURRENT EDIT'
                self.page.verified_at = None  # A1 auto-clear invariant (fresh clear)
                self.page.verified_by_id = None
                self.page.verify_owner_id = None
                self.page.version += 1
                self.page.save()
                return real_sfu(*args, **kwargs)
            sfu.side_effect = _race
            resp = self.c_editor.patch(self.url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT, resp.content)
        self.assertEqual(resp.data['error'], 'verify_conflict')
        self.page.refresh_from_db()
        # the cleared state was NOT resurrected
        self.assertIsNone(self.page.verified_at)
        self.assertIn('REWRITTEN', self.page.content_text)

    def test_verify_edit_reverify_round_trip(self):
        """S-B: verify → content edit clears in the same write → re-verify stamps again."""
        first = self.c_editor.patch(self.url, {}, format='json')
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.content)
        edit = self.c_editor.patch(
            self.page_url,
            {'content_text': '# H1\n\nbody edited', 'content_json': {'type': 'doc'}},
            format='json',
        )
        self.assertEqual(edit.status_code, status.HTTP_200_OK, edit.content)
        self.page.refresh_from_db()
        self.assertIsNone(self.page.verified_at)
        self.assertIsNone(self.page.verified_by_id)
        self.assertIsNone(self.page.verify_owner_id)
        again = self.c_editor.patch(self.url, {}, format='json')
        self.assertEqual(again.status_code, status.HTTP_200_OK, again.content)
        self.assertEqual(again.data['verified_by_id'], self.editor.id)
        self.assertEqual(again.data['verify_owner_id'], self.editor.id)
        self.page.refresh_from_db()
        self.assertIsNotNone(self.page.verified_at)

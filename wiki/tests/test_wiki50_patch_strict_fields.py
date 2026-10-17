"""WIKI-50: page PATCH must reject unknown write fields and never consume a
version for a byte-identical write (no phantom no-diff revisions)."""
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from wiki.models import Page, PageVersion, Space

User = get_user_model()


class PagePatchStrictFieldsTests(APITestCase):
    """Regression matrix for SCLI/WIKI-50 acceptance:

    1. ``content`` (unknown field) → 4xx naming it, version/bytes unchanged.
    2. ``content_text`` only → 200, version+1, bytes changed.
    3. ``content`` + ``content_text`` present/disagreeing → 4xx, version unchanged.
    4. Unknown field → 4xx, version unchanged.
    5. Real ``title``/``status``/``labels`` writes → version+1 (and no-op variants
       do NOT bump — a write that changes nothing must not consume a version).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        self.client = APIClient(HTTP_X_ORGANIZATION_ID='1')
        self.user = User.objects.create_user(
            username='wiki50', email='wiki50@example.com', password='x',
            is_staff=True, is_superuser=True,
        )
        self.client.force_authenticate(user=self.user)
        self.space = Space.objects.create(
            organization_id=1, key='ENG', name='Engineering',
            visibility='org', owner_id=self.user.id,
        )
        self.page = Page.objects.create(
            space=self.space, title='WIKI-50 Page',
            content_text='line one\nline two\nline three',
            content_json={}, status='draft', created_by_id=self.user.id,
        )
        self.url = f'/api/pages/{self.page.id}/'

    def _patch(self, payload):
        return self.client.patch(self.url, payload, format='json')

    def _reload(self):
        # Return a FRESH instance — refresh_from_db() mutates self.page in
        # place, so `before` and `after` reloads would alias the same object
        # (reloading `after` would also rewrite what `before` reads).
        self.page.refresh_from_db()
        return Page.objects.get(pk=self.page.pk)

    def _version_count(self):
        return PageVersion.objects.filter(page=self.page).count()

    # ── Acceptance 1/2/3/4: unknown fields + content alias ──

    def test_patch_with_content_only_is_rejected_naming_field_and_preserves_state(self):
        before = self._reload()
        vcount_before = self._version_count()

        resp = self._patch({'content': '# Brand new markdown'})

        self.assertEqual(resp.status_code, 400, resp.content)
        body = resp.data
        self.assertIn('content', body)
        self.assertIn('Unrecognized write field "content"', body['content'][0])
        after = self._reload()
        self.assertEqual(after.version, before.version)
        self.assertEqual(after.content_text, before.content_text)
        self.assertEqual(self._version_count(), vcount_before)

    def test_patch_with_content_text_only_persists_and_bumps_version(self):
        before = self._reload()
        new_body = before.content_text + '\nappended line'

        resp = self._patch({'content_text': new_body})

        self.assertEqual(resp.status_code, 200, resp.content)
        after = self._reload()
        self.assertEqual(after.version, before.version + 1)
        self.assertEqual(after.content_text, new_body)
        self.assertEqual(self._version_count(), 1)  # one real PageVersion added

    def test_patch_with_content_and_disagreeing_content_text_is_rejected(self):
        before = self._reload()
        resp = self._patch({'content': '# A', 'content_text': 'B'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('content', resp.data)
        after = self._reload()
        self.assertEqual(after.version, before.version)
        self.assertEqual(after.content_text, before.content_text)

    def test_patch_with_unknown_field_is_rejected(self):
        before = self._reload()
        resp = self._patch({'bogus_field': 1})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('bogus_field', resp.data)
        self.assertEqual(self._reload().version, before.version)

    # ── Acceptance 2: no-op writes must not consume a version ──

    def test_patch_identical_content_does_not_bump_version(self):
        before = self._reload()
        resp = self._patch({'content_text': before.content_text})
        self.assertEqual(resp.status_code, 200, resp.content)
        after = self._reload()
        self.assertEqual(after.version, before.version)
        self.assertEqual(self._version_count(), 0)

    def test_patch_empty_body_does_not_bump_version(self):
        before = self._reload()
        resp = self._patch({})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._reload().version, before.version)
        self.assertEqual(self._version_count(), 0)

    def test_patch_same_status_does_not_bump_but_changed_status_does(self):
        before = self._reload()
        self.assertEqual(before.status, 'draft')
        resp = self._patch({'status': 'draft'})  # no-op
        self.assertEqual(resp.status_code, 200, resp.content)
        after_noop = self._reload()
        self.assertEqual(after_noop.version, before.version)

        resp = self._patch({'status': 'published'})  # real change
        self.assertEqual(resp.status_code, 200, resp.content)
        after_write = self._reload()
        self.assertEqual(after_write.version, before.version + 1)
        self.assertEqual(after_write.status, 'published')
        self.assertEqual(self._version_count(), 1)

    def test_patch_title_real_change_bumps_and_persists(self):
        before = self._reload()
        resp = self._patch({'title': 'Renamed'})
        self.assertEqual(resp.status_code, 200, resp.content)
        after = self._reload()
        self.assertEqual(after.title, 'Renamed')
        self.assertEqual(after.version, before.version + 1)

    # ── Acceptance 2/4: labels are a real write surface; no-op labels don't bump ──

    def test_label_write_bumps_version_and_identical_labels_do_not(self):
        from wiki.models import Label
        label = Label.objects.create(organization_id=1, name='docs', color='#00ff00')

        before = self._reload()
        resp = self._patch({'label_ids': [label.id]})  # real change
        self.assertEqual(resp.status_code, 200, resp.content)
        after_add = self._reload()
        self.assertEqual(after_add.version, before.version + 1)

        resp = self._patch({'label_ids': [label.id]})  # no-op
        self.assertEqual(resp.status_code, 200, resp.content)
        after_noop = self._reload()
        self.assertEqual(after_noop.version, after_add.version)

    # ── Control fields remain accepted and still 409 on a real conflict ──

    def test_control_fields_and_stale_expected_version_behavior_preserved(self):
        before = self._reload()
        # control field alone → no-op (no version consumed), still 200
        resp = self._patch({'change_message': 'a note', 'title': before.title})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._reload().version, before.version)

        # real write with matching expected_version → applies + bumps
        resp = self._patch({'content_text': 'edited once', 'expected_version': before.version})
        self.assertEqual(resp.status_code, 200, resp.content)
        after_apply = self._reload()
        self.assertEqual(after_apply.version, before.version + 1)
        self.assertEqual(after_apply.content_text, 'edited once')

        # stale expected_version → 409 conflict, no version consumed
        resp = self._patch({'content_text': 'edited again', 'expected_version': before.version})
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(self._reload().version, after_apply.version)

"""WIKI-126 (Slice A4): verification badges on search / backlinks / list
surfaces — with the SCS-239 authenticated-paths-only guard.

Design: WIKI-123 §6 (canonical, `0a587b74` v2). Hard requirement: badge and
verification metadata render ONLY on authenticated read paths. SCS-239
removed anonymous reads entirely (IsAuthenticatedOrPublicReadOnly is gone),
so an unauthenticated caller gets 401 and never a payload that could carry
verification fields.

Surfaces under test:
  - search rows      → SearchResultSerializer(view builds dicts + context)
  - backlinks rows   → PageListSerializer (shared with children/related)
  - page detail      → PageDetailSerializer (guard from WIKI-124, re-proven here)
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from wiki.models import Page, Space

User = get_user_model()


class Wiki126BadgeSurfaceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='n126', email='n126@example.com', password='x',
            first_name='N', last_name='126',
        )
        self.user.organization_memberships = {1: 'member'}
        # PUBLIC space: anonymous callers can read it — the leak surface.
        self.space = Space.objects.create(
            organization_id=1, key='PUB', name='Public', owner_id=self.user.id,
            visibility='public')
        self.verified_page = Page.objects.create(
            space=self.space, title='Verified Ledger', position=0,
            created_by_id=self.user.id,
            content_text='# H\n\nbody', content_json={'type': 'doc', 'content': []},
        )
        self.verified_page.verified_at = timezone.now() - timedelta_days(12)
        self.verified_page.verified_by_id = self.user.id
        self.verified_page.verify_owner_id = self.user.id
        self.verified_page.save()
        self.unverified_page = Page.objects.create(
            space=self.space, title='Fresh Draft', position=1,
            created_by_id=self.user.id,
            content_text='# H2\n\nbody2', content_json={'type': 'doc', 'content': []},
        )
        # backlink: fresh -> verified
        from wiki.models import PageLink
        PageLink.objects.create(source_page=self.unverified_page, target_page=self.verified_page)
        self.client = APIClient()

    # -- helpers ---------------------------------------------------------

    def _auth(self):
        self.client.force_authenticate(user=self.user)

    def _anon(self):
        self.client.force_authenticate(user=None)

    def _search(self):
        # 'Ledger' matches the verified page's TITLE via the icontains
        # fallback (FTS vectors are engine-specific in tests) — the badge
        # surface is what's under test, not ranking.
        return self.client.get('/api/search/', {'q': 'Ledger'}, format='json')

    # -- search surface ---------------------------------------------------

    def test_search_anonymous_has_no_verification_fields(self):
        self._anon()
        resp = self._search()
        # SCS-239: anonymous reads are rejected, so there is no row payload.
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertNotIn('verified', resp.data)

    def test_search_authenticated_sees_correct_state(self):
        self._auth()
        resp = self._search()
        self.assertEqual(resp.status_code, 200, resp.content)
        by_title = {row['title']: row for row in resp.data}
        self.assertIn('verified', by_title['Verified Ledger'])
        self.assertTrue(by_title['Verified Ledger']['verified'])
        self.assertIsNotNone(by_title['Verified Ledger']['verified_at'])
        if 'Fresh Draft' in by_title:
            self.assertFalse(by_title['Fresh Draft']['verified'])
            self.assertIsNone(by_title['Fresh Draft']['verified_at'])

    # -- backlinks surface -------------------------------------------------

    def test_backlinks_authenticated_carries_badge_fields(self):
        self._auth()
        resp = self.client.get(
            f'/api/pages/{self.verified_page.id}/backlinks/', format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        # rows are pages linking TO the target; verified fields must exist
        # on the row schema even when the list is empty.
        for row in resp.data:
            self.assertIn('verified', row)
            self.assertIn('verified_at', row)

    def test_backlinks_anonymous_has_no_verification_fields(self):
        self._anon()
        resp = self.client.get(
            f'/api/pages/{self.verified_page.id}/backlinks/', format='json')
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertNotIn('verified', resp.data)

    # -- page detail (guard re-proof on the A1 surface) ---------------------

    def test_detail_authenticated_carries_verification_state(self):
        self._auth()
        resp = self.client.get(f'/api/pages/{self.verified_page.id}/', format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data['verified'])
        self.assertIsNotNone(resp.data['verified_at'])
        self.assertEqual(resp.data['verified_by'], self.user.id)

    def test_detail_anonymous_has_no_verification_fields(self):
        self._anon()
        resp = self.client.get(f'/api/pages/{self.verified_page.id}/', format='json')
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertNotIn('verified', resp.data)


def timedelta_days(n):
    from datetime import timedelta
    return timedelta(days=n)

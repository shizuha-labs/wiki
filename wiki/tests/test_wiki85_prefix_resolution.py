"""WIKI-85: server-side partial-ID prefix resolution regression test.

The MCP `wiki_get_page` timed out on every lookup because the client walked
every paginated /pages/ page in Python (1400+ pages at 20/page) to resolve a
partial UUID — exceeding the 30s MCP timeout. The fix moves prefix resolution
to a SINGLE server-side query (`/api/pages/?prefix=`).

This test asserts the backend filters on the UUID prefix in one request, so a
page beyond the first pagination page is resolvable without a client-side walk.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from wiki.models import Page, Space

User = get_user_model()


class Wiki85PrefixResolutionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='nagi', email='nagi@example.com', password='x',
            is_staff=False,
        )
        self.user.organization_memberships = {1: 'member'}
        self.space = Space.objects.create(
            organization_id=1, key='QA', name='QA', owner_id=self.user.id,
            visibility='org',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _make_page(self, pid, title):
        return Page.objects.create(
            id=pid, space=self.space, title=title, status='published',
            content_text=f'Content {title}', created_by_id=self.user.id,
        )

    def test_prefix_filter_returns_matching_pages(self):
        target = self._make_page(
            '1845935e-c5aa-450d-9bf9-73544100a4be', 'Books Overview',
        )
        self._make_page(
            'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', 'Other Page',
        )
        resp = self.client.get('/api/pages/', {'prefix': '1845935e'})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.data.get('results', resp.data)
        ids = {p['id'] for p in data}
        self.assertIn(str(target.id), ids)
        self.assertNotIn('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', ids)

    def test_prefix_filter_is_case_insensitive(self):
        target = self._make_page(
            '82a246fa-257a-4e2d-8f01-9799745c8365', 'QA Operating Model',
        )
        resp = self.client.get('/api/pages/', {'prefix': '82A246FA'})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.data.get('results', resp.data)
        self.assertEqual([p['id'] for p in data], [str(target.id)])

    def test_short_prefix_is_ignored(self):
        self._make_page(
            '1845935e-c5aa-450d-9bf9-73544100a4be', 'Books Overview',
        )
        # Prefixes shorter than 4 chars are not filtered (avoid huge scans) —
        # the full list is returned, matching the pre-fix behavior.
        resp = self.client.get('/api/pages/', {'prefix': '18'})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.data.get('results', resp.data)
        self.assertGreaterEqual(len(data), 1)

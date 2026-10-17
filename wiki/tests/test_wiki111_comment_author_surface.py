"""WIKI-111 regression: the comment payload must carry the author identity.

Focused-QA fingerprint (2026-09-18): comments created by an authenticated MCP
user render the author as fallback "User #15" in the Wiki Comments UI while the
page-author control renders the real identity — the comment payload had no
author surface a consumer can render as a name (WIKI-53 stopped at author_id,
which no consumer renders as a name; the frontend literally printed
"User #{created_by_id}").

Fix under test: CommentViewSet list/retrieve inject author_email/author_name
resolved from the shizuha-id directory in ONE batched call
(/api/internal/users/?ids=…, forwarded-caller pattern), TTL-cached, and
fail-open — a directory outage must degrade to the id-only payload, never
block the comment list. Nested replies get the same surface.
"""
from unittest.mock import MagicMock, patch

import requests as _requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from wiki.models import Page, Space
from wiki.views import _author_identity_cache

User = get_user_model()


class Wiki111CommentAuthorSurfaceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The Postgres FTS search-vector post_save signal (to_tsvector) is
        # PG-only and orthogonal to the author-surface logic; disconnect it so
        # the suite runs on any backend (same pattern as the cleanup-sweep and
        # crosslink suites).
        from django.db.models.signals import post_save
        from wiki.signals import update_search_vector
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        from django.db.models.signals import post_save
        from wiki.signals import update_search_vector
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        _author_identity_cache.clear()
        self.user_a = User.objects.create_user(
            username='zen', email='zen@example.com', password='x',
            first_name='Zen', last_name='',
        )
        self.user_a.organization_memberships = {1: 'member'}
        self.s1 = Space.objects.create(organization_id=1, key='ENG', name='Eng',
                                       owner_id=self.user_a.id, visibility='org')
        self.p1 = Page.objects.create(space=self.s1, title='Design SoT', position=0,
                                      created_by_id=self.user_a.id)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user_a)
        self.directory_user = {
            'id': self.user_a.id,
            'username': 'zen',
            'email': 'zen@shizuha.com',
            'first_name': 'Zen',
            'last_name': '',
        }

    def _directory_response(self, results):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'count': len(results), 'results': results}
        return resp

    def test_list_injects_author_identity_with_one_batched_call(self):
        self.client.post(f'/api/pages/{self.p1.id}/comments/',
                         {'content': 'root', 'parent': None}, format='json')
        with patch('requests.get', return_value=self._directory_response([self.directory_user])) as mock_get:
            resp = self.client.get(f'/api/comments/?page_id={self.p1.id}')
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.data['results']
        self.assertTrue(results)
        self.assertEqual(results[0]['author_email'], 'zen@shizuha.com')
        self.assertEqual(results[0]['author_name'], 'Zen')
        mock_get.assert_called_once()  # one batched directory call for the cold set
        params = mock_get.call_args.kwargs.get('params') or mock_get.call_args.args[1]
        self.assertIn(str(self.user_a.id), str(params.get('ids')))

    def test_retrieve_injects_author_identity(self):
        created = self.client.post(f'/api/pages/{self.p1.id}/comments/',
                                   {'content': 'root', 'parent': None}, format='json')
        comment_id = created.data['id']
        with patch('requests.get', return_value=self._directory_response([self.directory_user])):
            resp = self.client.get(f'/api/comments/{comment_id}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['author_email'], 'zen@shizuha.com')
        self.assertEqual(resp.data['author_name'], 'Zen')

    def test_nested_replies_get_the_same_surface(self):
        top = self.client.post(f'/api/pages/{self.p1.id}/comments/',
                               {'content': 'root', 'parent': None}, format='json')
        self.client.post(f'/api/pages/{self.p1.id}/comments/',
                         {'content': 'threaded reply', 'parent': top.data['id']}, format='json')
        with patch('requests.get', return_value=self._directory_response([self.directory_user])):
            resp = self.client.get(f'/api/comments/?page_id={self.p1.id}')
        self.assertEqual(resp.status_code, 200, resp.content)
        top_row = next(r for r in resp.data['results'] if r['id'] == top.data['id'])
        self.assertTrue(top_row['replies'])
        self.assertEqual(top_row['replies'][0]['author_name'], 'Zen')

    def test_directory_outage_degrades_fail_open(self):
        self.client.post(f'/api/pages/{self.p1.id}/comments/',
                         {'content': 'root', 'parent': None}, format='json')
        with patch('requests.get', side_effect=_requests.RequestException('directory down')):
            resp = self.client.get(f'/api/comments/?page_id={self.p1.id}')
        self.assertEqual(resp.status_code, 200, resp.content)  # never blocks the list
        results = resp.data['results']
        self.assertTrue(results)
        self.assertNotIn('author_email', results[0])
        self.assertNotIn('author_name', results[0])
        # The id-only surface consumers already render stays intact.
        self.assertEqual(results[0]['created_by_id'], self.user_a.id)

    def test_warm_cache_skips_the_second_directory_call(self):
        self.client.post(f'/api/pages/{self.p1.id}/comments/',
                         {'content': 'root', 'parent': None}, format='json')
        with patch('requests.get', return_value=self._directory_response([self.directory_user])) as mock_get:
            first = self.client.get(f'/api/comments/?page_id={self.p1.id}')
            second = self.client.get(f'/api/comments/?page_id={self.p1.id}')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        mock_get.assert_called_once()  # TTL cache serves the second list
        self.assertEqual(second.data['results'][0]['author_name'], 'Zen')


class Wiki121PageScopedCommentAuthorSurfaceTests(Wiki111CommentAuthorSurfaceTests):
    """WIKI-121 regression (third occurrence of the WIKI-53 → WIKI-111 family).

    Rollout `5671ceee42a3` re-broke the family on the page-scoped comment
    routes: `GET /api/pages/{id}/comments/` (the Comments UI's own list read)
    and the create response returned the bare `PageCommentSerializer` payload
    with no author surface, so MCP-authored comments rendered the
    "User #<id>" fallback while `/api/comments/{id}/` resolved correctly —
    per-comment view discriminating that the data exists. The WIKI-111
    enrichment had been applied only to `CommentViewSet`; this pins the
    page-scoped action to the same contract so the drift cannot re-enter.
    """

    def test_page_scoped_list_injects_author_identity(self):
        self.client.post(f'/api/pages/{self.p1.id}/comments/',
                         {'content': 'root', 'parent': None}, format='json')
        with patch('requests.get', return_value=self._directory_response([self.directory_user])):
            resp = self.client.get(f'/api/pages/{self.p1.id}/comments/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data)
        self.assertEqual(resp.data[0]['author_email'], 'zen@shizuha.com')
        self.assertEqual(resp.data[0]['author_name'], 'Zen')

    def test_page_scoped_create_response_injects_author_identity(self):
        with patch('requests.get', return_value=self._directory_response([self.directory_user])):
            resp = self.client.post(f'/api/pages/{self.p1.id}/comments/',
                                    {'content': 'root', 'parent': None}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data['author_email'], 'zen@shizuha.com')
        self.assertEqual(resp.data['author_name'], 'Zen')

    def test_page_scoped_list_degrades_fail_open_on_directory_outage(self):
        self.client.post(f'/api/pages/{self.p1.id}/comments/',
                         {'content': 'root', 'parent': None}, format='json')
        with patch('requests.get', side_effect=_requests.RequestException('directory down')):
            resp = self.client.get(f'/api/pages/{self.p1.id}/comments/')
        self.assertEqual(resp.status_code, 200, resp.content)  # never blocks the list
        self.assertTrue(resp.data)
        self.assertNotIn('author_email', resp.data[0])
        self.assertNotIn('author_name', resp.data[0])
        self.assertEqual(resp.data[0]['created_by_id'], self.user_a.id)

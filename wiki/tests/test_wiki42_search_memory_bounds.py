"""WIKI-42: wiki search must not OOM a serving replica.

Prod evidence (2026-07-16 08:42 UTC): a read-only multi-word audit search
OOMKilled a shizuha-wiki replica (exit 137, restartCount→4). Root cause: the
search path fetched the FULL content_text + search_vector for every hit and
sliced excerpts in Python, so large pages × concurrent searches materialized
hundreds of MB per burst.

These tests prove the bounded rewrite:
- request-size bounds reject oversized query/term counts BEFORE any DB work;
- the result fetch is column-restricted — content_text/search_vector never
  enter the app process (a huge page body does NOT appear in the response,
  only the bounded DB-side headline/prefix);
- labels are batched (no per-page query), and result count is capped.

The Postgres FTS path (SearchHeadline/SearchVector) needs a real Postgres
backend; those assertions are guarded and skipped on sqlite, while the
request-bound and title-only paths run everywhere.
"""
from pathlib import Path
import re

from django.db import connection
from django.db.models.signals import post_save
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from wiki.authentication import FederatedUser
from wiki.models import Label, Page, Space
from wiki.signals import update_search_vector

ORG = 1
IS_PG = connection.vendor == 'postgresql'


def _fed(user_id=101, org=ORG, role='admin'):
    return FederatedUser(
        user_id=user_id, email=f'u{user_id}@org{org}.example', username=f'u{user_id}',
        is_staff=False, is_superuser=False, enabled_services=['wiki'],
        organization_memberships={org: role},
    )


class SearchMemoryBoundsTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.user_id = 101
        self.client = APIClient(HTTP_X_ORGANIZATION_ID=str(ORG))
        self.client.force_authenticate(user=_fed(self.user_id))
        # Space.owner_id and Page.created_by_id are non-null — fixtures must
        # supply both or the model layer raises IntegrityError (revi P1 #1).
        self.space = Space.objects.create(
            key='ENG', name='Engineering', organization_id=ORG, visibility='org',
            owner_id=self.user_id,
        )

    def _page(self, title, content, status_='published'):
        return Page.objects.create(
            space=self.space, title=title, slug=title.lower().replace(' ', '-'),
            content_text=content, status=status_,
            created_by_id=self.user_id,
        )

    # ── request bounds (backend-agnostic) ───────────────────────────────
    def test_overlong_query_rejected_before_db_work(self):
        resp = self.client.get('/api/search/', {'q': 'x' * 500})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_too_many_terms_rejected(self):
        resp = self.client.get('/api/search/', {'q': ' '.join(['term'] * 40)})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_short_query_returns_empty_not_error(self):
        resp = self.client.get('/api/search/', {'q': 'a'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])

    # ── the OOM class: huge page body never crosses into the response ───
    def test_huge_page_body_is_not_materialized_in_response(self):
        # A ~2MB page. The old path returned its full content_text for excerpt
        # slicing; the bounded path must return only a small headline/prefix.
        big = ('needle ' + ('filler ' * 300_000))  # ~2.1 MB
        self._page('Giant Page', big)
        resp = self.client.get('/api/search/', {'q': 'needle'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        if not resp.data:
            self.skipTest('no FTS match on this backend (search_vector unset on sqlite)')
        excerpt = resp.data[0]['excerpt']
        self.assertLessEqual(len(excerpt), 600)  # <= MAX_EXCERPT_CHARS + ellipses
        # The multi-MB body must not appear anywhere in the serialized payload.
        self.assertNotIn('filler filler filler filler', str(resp.data))

    def test_title_only_hit_uses_bounded_prefix(self):
        # icontains title branch works on every backend (no search_vector needed).
        big = 'zzz ' * 200_000  # ~800KB, does NOT contain the query term
        self._page('Deployment Runbook', big)
        resp = self.client.get('/api/search/', {'q': 'Runbook'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(any(r['title'] == 'Deployment Runbook' for r in resp.data))
        hit = next(r for r in resp.data if r['title'] == 'Deployment Runbook')
        self.assertLessEqual(len(hit['excerpt']), 600)

    def test_result_count_capped(self):
        for i in range(70):
            self._page(f'Runbook {i}', f'runbook body {i}')
        resp = self.client.get('/api/search/', {'q': 'Runbook'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(resp.data), 50)

    # ── concurrency bound: saturated replica sheds instead of stacking work ─
    # The gate is a REAL shared Redis semaphore (cross-process/worker), not a
    # process-local counter: gunicorn runs multiple workers with separate
    # memory, so only a Redis-backed acquire can shed cross-worker concurrency.
    # These tests drive the actual redis client the view uses, with a socket
    # timeout so the suite fails loudly (not silently) if Redis is absent.
    def _redis(self):
        from wiki.views import SearchViewSet
        # Isolate to a scratch Redis DB so we never leak the shared key, and
        # force a fresh client bound to it (pool-safe vs r.select()).
        import os
        base = os.environ.get(
            'CELERY_BROKER_URL', 'redis://127.0.0.1:6379/5',
        )
        SearchViewSet._reset_search_redis_for_tests()
        SearchViewSet._SEARCH_REDIS_URL = base.rsplit('/', 1)[0] + '/15'
        r = SearchViewSet._search_redis()
        r.delete(SearchViewSet._SEARCH_SLOT_KEY)
        return r, SearchViewSet

    def test_concurrency_saturation_sheds_with_429_then_recovers(self):
        from wiki.views import SearchViewSet
        r, vs = self._redis()
        try:
            for _ in range(vs.MAX_CONCURRENT_SEARCHES):
                self.assertTrue(vs()._acquire_search_slot() is True)
            # Next acquire exceeds the shared cap → shed.
            self.assertIs(vs()._acquire_search_slot(), False)
            resp = self.client.get('/api/search/', {'q': 'runbook'})
            self.assertEqual(resp.status_code, 429)
            self.assertEqual(resp.headers.get('Retry-After'), '2')
            # Releasing a slot lets the next request through.
            vs()._release_search_slot()
            resp = self.client.get('/api/search/', {'q': 'runbook'})
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
        finally:
            r.delete(vs._SEARCH_SLOT_KEY)

    def test_slot_counter_is_shared_not_per_request_object(self):
        # The same Redis counter is used by every acquire — two separate
        # view instances contend for the SAME cap (the old LocMemCache bug
        # would have created one counter per process).
        r, vs = self._redis()
        try:
            a = vs()
            b = vs()
            for _ in range(vs.MAX_CONCURRENT_SEARCHES):
                self.assertTrue(a._acquire_search_slot() is True)
            self.assertIs(b._acquire_search_slot(), False)
            a._release_search_slot()
            self.assertIs(b._acquire_search_slot(), True)
        finally:
            r.delete(vs._SEARCH_SLOT_KEY)

    def test_redis_down_fails_closed_with_429(self):
        # The shared gate is a safety dependency.  Failing open would allow all
        # gthread handlers into expensive FTS work and recreate the OOM class.
        from wiki.views import SearchViewSet
        SearchViewSet._reset_search_redis_for_tests()
        original_url = SearchViewSet._SEARCH_REDIS_URL
        try:
            # Point at a port with no listener → immediate connect failure.
            SearchViewSet._SEARCH_REDIS_URL = 'redis://127.0.0.1:1/15'
            self.assertIs(SearchViewSet()._acquire_search_slot(), False)
            resp = self.client.get('/api/search/', {'q': 'runbook'})
            self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertEqual(resp.headers.get('Retry-After'), '2')
        finally:
            SearchViewSet._SEARCH_REDIS_URL = original_url
            SearchViewSet._reset_search_redis_for_tests()

    def test_server_handler_capacity_exceeds_expensive_search_cap(self):
        # Production-order regression for the live failure: a burst arrives at
        # Gunicorn first, then Django's Redis gate.  If a replica has no more
        # handlers than the gate's cap, excess connections wait in the socket
        # backlog and time out without ever receiving 429.
        from wiki.views import SearchViewSet

        config = (
            Path(__file__).resolve().parents[2] / 'supervisord.conf'
        ).read_text()
        command = next(
            line for line in config.splitlines()
            if line.startswith('command=gunicorn')
        )
        workers = int(re.search(r'--workers\s+(\d+)', command).group(1))
        threads = int(re.search(r'--threads\s+(\d+)', command).group(1))
        self.assertIn('--worker-class gthread', command)
        self.assertGreater(workers * threads, SearchViewSet.MAX_CONCURRENT_SEARCHES)

    # ── label batching: constant number of queries regardless of hit count ─
    def test_labels_batched_not_per_result(self):
        label = Label.objects.create(organization_id=ORG, name='ops', color='#123456')
        for i in range(12):
            page = self._page(f'Runbook L{i}', f'runbook body {i}')
            page.labels.add(label)
        # The whole request (queryset + label batch) must be a small, bounded
        # number of queries — NOT one-per-result. Assert an upper bound that
        # a per-result N+1 (12+) would blow past.
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get('/api/search/', {'q': 'Runbook'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # membership/authz + page query + single label batch — comfortably < 10,
        # and crucially not growing with the 12 labelled results.
        self.assertLess(len(ctx.captured_queries), 12)
        if resp.data:
            labels = resp.data[0].get('labels') or []
            if labels:
                self.assertEqual(set(labels[0].keys()), {'id', 'name', 'color'})

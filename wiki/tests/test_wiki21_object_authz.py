"""
WIKI-21 negative-authz regressions (PLAT-1247 trust-boundary probes).

Three object-level authorization gaps let an authenticated user in org X
read/modify another space/org's data via a client-supplied id. Each test must
FAIL before the fix (200 / data leak) and PASS after.
"""
import threading
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient, APITestCase

from wiki.models import Space, Page, PageComment
from wiki.views import PageViewSet

User = get_user_model()


class WikiObjectAuthzTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The PG-only FTS search-vector post_save signal is orthogonal here.
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
        # User A: non-staff, member of org 1 only.
        self.user_a = User.objects.create_user(
            username='attacker', email='a@example.com', password='x', is_staff=False,
        )
        self.user_a.organization_memberships = {1: 'member'}

        # A's own space/pages (org 1) — A owns S1 so A can see + move them.
        self.s1 = Space.objects.create(organization_id=1, key='ENG', name='Eng',
                                       owner_id=self.user_a.id, visibility='org')
        self.p1a = Page.objects.create(space=self.s1, title='A1', position=0,
                                       created_by_id=self.user_a.id)
        self.p1b = Page.objects.create(space=self.s1, title='A2', position=1,
                                       created_by_id=self.user_a.id)

        # A restricted space/page in ANOTHER org (org 2) — A is not a member.
        self.s2 = Space.objects.create(organization_id=2, key='SEC', name='Secret',
                                       owner_id=999, visibility='org')
        self.p2 = Page.objects.create(space=self.s2, title='Secret Page', position=0,
                                      created_by_id=999)
        self.secret_comment = PageComment.objects.create(
            page=self.p2, content='confidential', created_by_id=999,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user_a)

    def test_f1_cross_space_move_is_rejected(self):
        # A tries to reparent their P1a under P2 (a page in another org's space).
        resp = self.client.post(f'/api/pages/{self.p1a.id}/move/',
                                {'parent': str(self.p2.id)}, format='json')
        self.assertIn(resp.status_code, (403, 404))
        self.p1a.refresh_from_db()
        self.assertIsNone(self.p1a.parent_id)  # not reparented across tenants

    def test_f2_bulk_reorder_mixing_spaces_is_rejected(self):
        # A smuggles a restricted page (P2, other org) into a reorder batch.
        resp = self.client.post('/api/pages/reorder/',
                                {'page_ids': [str(self.p1a.id), str(self.p2.id)]},
                                format='json')
        self.assertIn(resp.status_code, (400, 403))
        # The restricted page's position must be untouched.
        self.p2.refresh_from_db()
        self.assertEqual(self.p2.position, 0)

    def test_f3_comment_list_on_restricted_page_is_empty(self):
        # A knows P2's UUID and asks for its comments.
        resp = self.client.get(f'/api/comments/?page_id={self.p2.id}')
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(results), 0)  # no leak of the confidential comment

    def test_own_space_operations_still_work(self):
        # Regression guard: A can still reorder within their own space.
        resp = self.client.post('/api/pages/reorder/',
                                {'page_ids': [str(self.p1b.id), str(self.p1a.id)]},
                                format='json')
        self.assertEqual(resp.status_code, 200)

    def test_same_org_cross_space_move_persists_complete_subtree(self):
        target = Space.objects.create(
            organization_id=1, key='QA', name='QA', owner_id=self.user_a.id,
            visibility='org',
        )
        child = Page.objects.create(
            space=self.s1, parent=self.p1a, title='A1 child', position=0,
            created_by_id=self.user_a.id,
        )

        resp = self.client.post(
            f'/api/pages/{self.p1a.id}/move/',
            {'space': str(target.id), 'position': 3},
            format='json',
        )

        self.assertEqual(resp.status_code, 200, resp.data)
        self.p1a.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(self.p1a.space_id, target.id)
        self.assertEqual(child.space_id, target.id)
        self.assertIsNone(self.p1a.parent_id)
        self.assertEqual(self.p1a.position, 3)
        self.assertEqual(child.parent_id, self.p1a.id)
        self.assertEqual(str(resp.data['space']), str(target.id))

    def test_cross_space_move_rejects_slug_collision_without_partial_write(self):
        target = Space.objects.create(
            organization_id=1, key='QA', name='QA', owner_id=self.user_a.id,
            visibility='org',
        )
        Page.objects.create(
            space=target, title=self.p1a.title, slug=self.p1a.slug,
            created_by_id=self.user_a.id,
        )

        resp = self.client.post(
            f'/api/pages/{self.p1a.id}/move/', {'space': str(target.id)}, format='json',
        )

        self.assertEqual(resp.status_code, 409, resp.data)
        self.p1a.refresh_from_db()
        self.assertEqual(self.p1a.space_id, self.s1.id)

    def test_cross_org_space_move_is_rejected(self):
        resp = self.client.post(
            f'/api/pages/{self.p1a.id}/move/', {'space': str(self.s2.id)}, format='json',
        )
        self.assertIn(resp.status_code, (403, 404))
        self.p1a.refresh_from_db()
        self.assertEqual(self.p1a.space_id, self.s1.id)

    def test_same_org_destination_without_write_access_is_rejected(self):
        target = Space.objects.create(
            organization_id=1, key='PRIVATE', name='Private', owner_id=999,
            visibility='private',
        )
        resp = self.client.post(
            f'/api/pages/{self.p1a.id}/move/', {'space': str(target.id)}, format='json',
        )
        self.assertIn(resp.status_code, (403, 404))
        self.p1a.refresh_from_db()
        self.assertEqual(self.p1a.space_id, self.s1.id)


class WikiMoveConcurrencyTests(TransactionTestCase):
    """PostgreSQL regression for attach-vs-cross-space-move serialization."""

    reset_sequences = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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
        self.user = User.objects.create_user(
            username='mover', email='mover@example.com', password='x', is_staff=False,
        )
        self.user.organization_memberships = {1: 'member'}
        self.source = Space.objects.create(
            organization_id=1, key='ENG', name='Eng', owner_id=self.user.id,
            visibility='org',
        )
        self.target = Space.objects.create(
            organization_id=1, key='QA', name='QA', owner_id=self.user.id,
            visibility='org',
        )
        self.root = Page.objects.create(
            space=self.source, title='Root', created_by_id=self.user.id,
        )

    def test_concurrent_child_attach_cannot_create_cross_space_edge(self):
        enumerated = threading.Event()
        release_move = threading.Event()
        results = {}
        original = PageViewSet._locked_subtree

        def paused_subtree(root):
            pages = original(root)
            enumerated.set()
            self.assertTrue(release_move.wait(5), 'test did not release move transaction')
            return pages

        def move_root():
            close_old_connections()
            client = APIClient()
            client.force_authenticate(user=self.user)
            results['move'] = client.post(
                f'/api/pages/{self.root.id}/move/',
                {'space': str(self.target.id)}, format='json',
            )
            close_old_connections()

        def attach_child():
            close_old_connections()
            client = APIClient()
            client.force_authenticate(user=self.user)
            results['attach'] = client.post(
                '/api/pages/',
                {
                    'space': str(self.source.id),
                    'parent': str(self.root.id),
                    'title': 'Concurrent child',
                    'content_json': {},
                    'content_text': '',
                    'status': 'published',
                },
                format='json',
            )
            close_old_connections()

        with patch.object(PageViewSet, '_locked_subtree', side_effect=paused_subtree):
            mover = threading.Thread(target=move_root)
            mover.start()
            self.assertTrue(enumerated.wait(5), 'move did not lock/enumerate subtree')

            attacher = threading.Thread(target=attach_child)
            attacher.start()
            time.sleep(0.2)
            self.assertTrue(attacher.is_alive(), 'child attach did not wait on parent row lock')

            release_move.set()
            mover.join(5)
            attacher.join(5)

        self.assertFalse(mover.is_alive())
        self.assertFalse(attacher.is_alive())
        self.assertEqual(results['move'].status_code, 200, results['move'].data)
        self.assertEqual(results['attach'].status_code, 400, results['attach'].data)
        self.root.refresh_from_db()
        self.assertEqual(self.root.space_id, self.target.id)
        self.assertFalse(
            Page.objects.filter(parent=self.root).exclude(space=self.target).exists(),
            'move reported success with a cross-space child edge',
        )

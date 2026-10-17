"""WIKI-38: same-space hierarchy invariant + health check command."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import F
from django.test import TestCase
from rest_framework.test import APIClient, APITestCase

from wiki.models import Page, PageVersion, Space

User = get_user_model()


def _page_kwargs(**extra):
    """Required Page fields for full_clean/save in tests (WIKI-38)."""
    base = {
        'content_json': {'type': 'doc', 'content': []},
        'created_by_id': 1,
        'updated_by_id': 1,
    }
    base.update(extra)
    return base


class Wiki38HierarchyInvariantTests(TestCase):
    def setUp(self):
        self.space_a = Space.objects.create(
            organization_id=1, key='SPA', name='Space A', owner_id=1, visibility='org'
        )
        self.space_b = Space.objects.create(
            organization_id=1, key='SPB', name='Space B', owner_id=1, visibility='org'
        )
        self.parent_a = Page.objects.create(
            **_page_kwargs(space=self.space_a, title='Parent A')
        )
        self.parent_b = Page.objects.create(
            **_page_kwargs(space=self.space_b, title='Parent B')
        )

    def test_same_space_parent_allowed(self):
        child = Page(
            **_page_kwargs(space=self.space_a, parent=self.parent_a, title='Child')
        )
        child.full_clean()
        child.save()
        self.assertEqual(child.parent_id, self.parent_a.id)

    def test_cross_space_parent_rejected_on_clean(self):
        child = Page(
            **_page_kwargs(space=self.space_a, parent=self.parent_b, title='Bad')
        )
        with self.assertRaises(ValidationError) as ctx:
            child.full_clean()
        self.assertIn('parent', ctx.exception.message_dict)

    def test_cross_space_parent_rejected_on_save(self):
        child = Page(
            **_page_kwargs(space=self.space_a, parent=self.parent_b, title='Bad Save')
        )
        with self.assertRaises(ValidationError):
            child.save()

    def test_check_command_ok_when_clean(self):
        Page.objects.create(
            **_page_kwargs(space=self.space_a, parent=self.parent_a, title='OK')
        )
        out = StringIO()
        call_command('check_hierarchy_invariants', stdout=out)
        self.assertIn('0 cross-space', out.getvalue())

    def test_check_command_fails_on_legacy_edge(self):
        child = Page.objects.create(
            **_page_kwargs(space=self.space_a, parent=self.parent_a, title='Legacy')
        )
        # Simulate legacy corruption bypassing model clean.
        Page.objects.filter(pk=child.pk).update(parent=self.parent_b)
        self.assertTrue(
            Page.objects.filter(parent__isnull=False)
            .exclude(space_id=F('parent__space_id'))
            .filter(pk=child.pk)
            .exists()
        )
        with self.assertRaises(CommandError):
            call_command('check_hierarchy_invariants', stdout=StringIO())


class Wiki38ApiWriteBoundaryTests(APITestCase):
    """WIKI-38 API write-boundary regressions (review P2).

    The same-space hierarchy invariant must hold at the real API write paths,
    not just Page.full_clean()/save():

    1. create in space A with a parent from space B is rejected WITHOUT a row;
    2. update/reparent of an existing page to a parent from another space is
       rejected WITHOUT mutating the page or creating a version.
    """

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
            username='owner', email='owner@example.com', password='x',
            is_staff=False,
        )
        self.user.organization_memberships = {1: 'member'}
        self.space_a = Space.objects.create(
            organization_id=1, key='SPA', name='Space A',
            owner_id=self.user.id, visibility='org',
        )
        self.space_b = Space.objects.create(
            organization_id=1, key='SPB', name='Space B',
            owner_id=self.user.id, visibility='org',
        )
        self.parent_a = Page.objects.create(
            **_page_kwargs(space=self.space_a, title='Parent A')
        )
        self.parent_b = Page.objects.create(
            **_page_kwargs(space=self.space_b, title='Parent B')
        )
        self.child = Page.objects.create(
            **_page_kwargs(space=self.space_a, parent=self.parent_a, title='Child')
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_api_create_with_cross_space_parent_is_rejected_without_row(self):
        before = Page.objects.count()
        resp = self.client.post(
            '/api/pages/',
            {
                'space': str(self.space_a.id),
                'parent': str(self.parent_b.id),
                'title': 'Bad Create',
                'content_json': {'type': 'doc', 'content': []},
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('parent', resp.data)
        # No row was created — the invariant holds at the API boundary.
        self.assertEqual(Page.objects.count(), before)
        self.assertFalse(
            Page.objects.filter(title='Bad Create').exists()
        )

    def test_api_update_reparent_to_cross_space_parent_rejected_without_mutation(self):
        before_versions = PageVersion.objects.filter(page=self.child).count()
        resp = self.client.patch(
            f'/api/pages/{self.child.id}/',
            {'parent': str(self.parent_b.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.child.refresh_from_db()
        # Parent unchanged — still the same-space parent.
        self.assertEqual(self.child.parent_id, self.parent_a.id)
        # No new version was created.
        self.assertEqual(
            PageVersion.objects.filter(page=self.child).count(), before_versions,
        )

    def test_api_update_reparent_to_same_space_parent_succeeds(self):
        other_a = Page.objects.create(
            **_page_kwargs(space=self.space_a, title='Other A')
        )
        resp = self.client.patch(
            f'/api/pages/{self.child.id}/',
            {'parent': str(other_a.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.child.refresh_from_db()
        self.assertEqual(self.child.parent_id, other_a.id)

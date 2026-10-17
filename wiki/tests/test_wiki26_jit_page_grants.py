"""WIKI-26: Admin JIT grants authorize scoped Handbook page updates."""
from unittest import mock

from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from django.db.models.signals import post_save

from wiki.authentication import FederatedUser
from wiki.models import Page, Space
from wiki.permissions import WikiPermissionService
from wiki.signals import update_search_vector


ORG_ID = 1
HANDBOOK_PAGE_ID = 'e63cf94b-9039-436d-a55f-ec5b6edb86fc'


def _fed(user_id=89):
    return FederatedUser(
        user_id=user_id,
        email=f'user{user_id}@shizuha.com',
        username=f'user{user_id}',
        is_staff=False,
        is_superuser=False,
        enabled_services=['wiki'],
        organization_memberships={ORG_ID: 'member'},
    )


def _client(user):
    client = APIClient(HTTP_X_ORGANIZATION_ID=str(ORG_ID))
    client.force_authenticate(user=user)
    return client


class WikiJITPageGrantTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.user = _fed()
        self.client = _client(self.user)
        self.space = Space.objects.create(
            organization_id=ORG_ID,
            key='HANDBOOK',
            name='Agent Handbook',
            visibility='org',
            owner_id=20,
        )
        self.page = Page.objects.create(
            id=HANDBOOK_PAGE_ID,
            space=self.space,
            title='Agent Handbook',
            content_text='v2',
            content_json={},
            status='published',
            created_by_id=20,
        )
        self.other_page = Page.objects.create(
            space=self.space,
            title='Other Handbook Page',
            content_text='other',
            content_json={},
            status='published',
            created_by_id=20,
        )

    @mock.patch.object(WikiPermissionService, '_fetch_live_jit_scoped_grants', return_value=[])
    def test_org_member_without_jit_grant_cannot_update_handbook_page(self, _fetch):
        resp = self.client.patch(
            f'/api/pages/{self.page.id}/',
            {'title': 'blocked'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'Agent Handbook')

        perms = self.client.get('/api/spaces/HANDBOOK/permissions/')
        self.assertEqual(perms.status_code, status.HTTP_200_OK)
        self.assertEqual(perms.data['role'], 'org_member')
        self.assertNotIn('update', perms.data.get('permissions', {}).get('page', []))

    @mock.patch.object(WikiPermissionService, '_fetch_live_jit_scoped_grants')
    def test_space_scoped_jit_grant_allows_handbook_page_update_and_permissions(self, fetch):
        fetch.return_value = [
            {'org_id': str(ORG_ID), 'scope': 'wiki.pages.update:HANDBOOK', 'role': 'admin'},
        ]

        perms = self.client.get('/api/spaces/HANDBOOK/permissions/')
        self.assertEqual(perms.status_code, status.HTTP_200_OK)
        self.assertEqual(perms.data['role'], 'org_member')
        self.assertIn('update', perms.data['permissions']['page'])

        resp = self.client.patch(
            f'/api/pages/{self.page.id}/',
            {'title': 'Agent Handbook v3'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'Agent Handbook v3')

    @mock.patch.object(WikiPermissionService, '_fetch_live_jit_scoped_grants')
    def test_page_scoped_jit_grant_allows_only_that_page(self, fetch):
        fetch.return_value = [
            {
                'org_id': str(ORG_ID),
                'scope': f'wiki.pages.update:HANDBOOK:{self.page.id}',
                'role': 'admin',
            },
        ]

        perms = self.client.get('/api/spaces/HANDBOOK/permissions/')
        self.assertEqual(perms.status_code, status.HTTP_200_OK)
        self.assertIn('update', perms.data['permissions']['page'])

        allowed = self.client.patch(
            f'/api/pages/{self.page.id}/',
            {'title': 'Agent Handbook v3'},
            format='json',
        )
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)

        denied = self.client.patch(
            f'/api/pages/{self.other_page.id}/',
            {'title': 'pwned'},
            format='json',
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        self.other_page.refresh_from_db()
        self.assertEqual(self.other_page.title, 'Other Handbook Page')

    @mock.patch.object(WikiPermissionService, '_fetch_live_jit_scoped_grants')
    def test_unrelated_jit_scope_does_not_authorize_handbook_update(self, fetch):
        fetch.return_value = [
            {'org_id': str(ORG_ID), 'scope': 'wiki.pages.delete:HANDBOOK', 'role': 'admin'},
            {'org_id': str(ORG_ID), 'scope': 'wiki.pages.update:ENG', 'role': 'admin'},
            {'org_id': '2', 'scope': 'wiki.pages.update:HANDBOOK', 'role': 'admin'},
        ]

        resp = self.client.patch(
            f'/api/pages/{self.page.id}/',
            {'title': 'blocked'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'Agent Handbook')

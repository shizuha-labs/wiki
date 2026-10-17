"""WIKI-54: wiki_list_spaces must honor the visibility filter.

Live QA failure: wiki_list_spaces(organization_id=1, visibility="private")
returned 20 spaces including org-visible ones — the backend ignored the
visibility query param. Expected: only spaces whose visibility equals the
requested value.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from wiki.models import Space

User = get_user_model()


class Wiki54SpaceVisibilityFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='mika', email='mika@example.com', password='x',
            is_staff=False,
        )
        self.user.organization_memberships = {1: 'member'}
        self.s1 = Space.objects.create(organization_id=1, key='PRIV', name='Private',
                                       owner_id=self.user.id, visibility='private')
        self.s2 = Space.objects.create(organization_id=1, key='ORG', name='Org',
                                       owner_id=999, visibility='org')
        self.s3 = Space.objects.create(organization_id=1, key='PUB', name='Public',
                                       owner_id=999, visibility='public')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _list(self, **params):
        resp = self.client.get('/api/spaces/', params)
        data = resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data
        return resp, data

    def test_private_filter_returns_only_private(self):
        resp, data = self._list(visibility='private')
        self.assertEqual(resp.status_code, 200, resp.content)
        keys = [s['key'] for s in data]
        self.assertEqual(keys, ['PRIV'])

    def test_org_filter_returns_only_org(self):
        resp, data = self._list(visibility='org')
        self.assertEqual(resp.status_code, 200, resp.content)
        keys = [s['key'] for s in data]
        self.assertEqual(keys, ['ORG'])

    def test_public_filter_returns_only_public(self):
        resp, data = self._list(visibility='public')
        self.assertEqual(resp.status_code, 200, resp.content)
        keys = [s['key'] for s in data]
        self.assertEqual(keys, ['PUB'])

    def test_no_filter_returns_all_visible(self):
        resp, data = self._list()
        self.assertEqual(resp.status_code, 200, resp.content)
        keys = sorted(s['key'] for s in data)
        self.assertEqual(keys, ['ORG', 'PRIV', 'PUB'])

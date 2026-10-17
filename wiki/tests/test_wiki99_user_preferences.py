"""WIKI-99: diagram prefs persist per Shizuha ID account, not per browser."""
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from wiki.models import UserPreference
from wiki.user_preferences import DIAGRAM_DEFAULTS, sanitize_diagrams

User = get_user_model()


class UserPreferenceAccountTests(APITestCase):
    def setUp(self):
        self.client = APIClient(HTTP_X_ORGANIZATION_ID='1')
        self.user = User.objects.create_user(
            username='wiki99a', email='wiki99a@example.com', password='x',
            is_staff=True, is_superuser=True,
        )
        self.other = User.objects.create_user(
            username='wiki99b', email='wiki99b@example.com', password='x',
            is_staff=True, is_superuser=True,
        )
        self.url = '/api/preferences/'

    def test_get_unauthenticated_is_denied(self):
        resp = self.client.get(self.url)
        self.assertIn(resp.status_code, (401, 403), resp.content)

    def test_get_empty_returns_defaults_not_persisted(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['diagrams'], DIAGRAM_DEFAULTS)
        self.assertEqual(body['diagrams']['scheme'], 'whiteboard')
        self.assertEqual(body['diagrams']['look'], 'handDrawn')
        self.assertFalse(body['persisted'])
        self.assertIsNone(body['updated_at'])
        self.assertFalse(UserPreference.objects.filter(pk=self.user.id).exists())

    def test_patch_persists_for_this_user_only(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(
            self.url,
            {'diagrams': {'look': 'neo', 'cornerRx': 4, 'scrollZoom': False}},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertTrue(body['persisted'])
        self.assertEqual(body['diagrams']['look'], 'neo')
        self.assertEqual(body['diagrams']['cornerRx'], 4)
        self.assertFalse(body['diagrams']['scrollZoom'])
        self.assertEqual(body['diagrams']['scheme'], 'whiteboard')
        self.assertIsNotNone(body['updated_at'])

        again = self.client.get(self.url)
        self.assertEqual(again.json()['diagrams']['look'], 'neo')
        self.assertEqual(again.json()['diagrams']['cornerRx'], 4)

        self.client.force_authenticate(user=self.other)
        other = self.client.get(self.url)
        self.assertEqual(other.status_code, 200, other.content)
        self.assertFalse(other.json()['persisted'])
        self.assertEqual(other.json()['diagrams']['look'], 'handDrawn')

    def test_patch_rejects_unknown_top_level_fields(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(self.url, {'theme': 'dark'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('theme', resp.json()['fields'])

    def test_patch_ignores_unknown_diagram_keys_and_clamps_rx(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(
            self.url,
            {'diagrams': {'look': 'neo', 'inject': '<script>', 'cornerRx': 99, 'scheme': 'nope'}},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        diagrams = resp.json()['diagrams']
        self.assertEqual(diagrams['look'], 'neo')
        self.assertEqual(diagrams['cornerRx'], 16)
        self.assertEqual(diagrams['scheme'], 'whiteboard')
        self.assertNotIn('inject', diagrams)

    def test_second_patch_merges_previous_keys(self):
        self.client.force_authenticate(user=self.user)
        self.client.patch(self.url, {'diagrams': {'look': 'neo'}}, format='json')
        resp = self.client.patch(self.url, {'diagrams': {'cornerRx': 4}}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        diagrams = resp.json()['diagrams']
        self.assertEqual(diagrams['look'], 'neo')
        self.assertEqual(diagrams['cornerRx'], 4)

    def test_sanitize_diagrams_unit(self):
        cleaned = sanitize_diagrams({'look': 'neo', 'scrollZoom': 'yes', 'cornerRx': '4'})
        self.assertEqual(cleaned['look'], 'neo')
        self.assertEqual(cleaned['cornerRx'], 4)
        self.assertTrue(cleaned['scrollZoom'])

    def test_patch_accepts_whiteboard_hand_drawn(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(
            self.url,
            {'diagrams': {'look': 'handDrawn', 'scheme': 'whiteboard'}},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        diagrams = resp.json()['diagrams']
        self.assertEqual(diagrams['look'], 'handDrawn')
        self.assertEqual(diagrams['scheme'], 'whiteboard')

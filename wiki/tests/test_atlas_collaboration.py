import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import TestCase
from rest_framework.test import APIClient

from wiki.authentication import FederatedUser
from wiki.models import Page, Space


class AtlasCollaborationTests(TestCase):
    def setUp(self):
        self.user = FederatedUser(user_id=89, username='atlas-reader', email='reader@example.com',
                                  enabled_services=['wiki'], organization_memberships={1: 'member'})
        self.space = Space.objects.create(organization_id=1, key='COLLAB', name='Architecture', owner_id=20, visibility='org')
        self.document = {'format': 'shizuha-atlas', 'version': 1, 'model': {'id': 'diagram'}}
        self.page = Page.objects.create(space=self.space, title='Design', created_by_id=20, status='published', content_json={
            'type': 'doc', 'content': [{'type': 'codeBlock', 'attrs': {'language': 'atlas'}, 'content': [{'type': 'text', 'text': json.dumps(self.document)}]}],
        })
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f'/api/atlas/collaboration/{self.page.id}/'
        self.payload = {'document_id': 'diagram', 'client_id': str(uuid4())}

    def post(self):
        return self.client.post(self.url, self.payload, format='json', HTTP_X_ORGANIZATION_ID='1')

    @patch('wiki.atlas_collaboration.collaboration_client')
    def test_presence_is_authorized_and_does_not_mutate_the_document(self, client):
        client.return_value.pipeline.return_value.__enter__.return_value.execute.return_value = [0, 1, True, True, []]
        before = Page.objects.values().get(pk=self.page.id)
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['version'], self.page.version)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(Page.objects.values().get(pk=self.page.id), before)

    @patch('wiki.atlas_collaboration.collaboration_client')
    def test_foreign_organization_is_rejected_before_presence_lookup(self, client):
        self.user.organization_memberships = {2: 'member'}
        self.assertEqual(self.post().status_code, 403)
        client.assert_not_called()

    @patch('wiki.atlas_collaboration.collaboration_client')
    def test_restricted_page_denied_even_to_organization_member(self, client):
        self.space.visibility = 'private'
        self.space.save()
        self.assertEqual(self.post().status_code, 404)
        client.assert_not_called()

    @patch('wiki.atlas_collaboration.collaboration_client')
    def test_unknown_document_and_malformed_client_do_not_touch_redis(self, client):
        self.payload['document_id'] = 'other'
        self.assertEqual(self.post().status_code, 400)
        self.payload['document_id'] = 'diagram'
        self.payload['client_id'] = '../../foreign'
        self.assertEqual(self.post().status_code, 400)
        client.assert_not_called()

    def test_anonymous_and_read_methods_are_not_accepted(self):
        self.assertIn(APIClient().post(self.url, self.payload, format='json').status_code, (401, 403))
        self.assertEqual(self.client.get(self.url).status_code, 405)

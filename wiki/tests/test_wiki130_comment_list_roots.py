"""WIKI-130: a reply must appear once, nested, not also as a list root."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from wiki.models import Page, Space

User = get_user_model()


class Wiki130CommentListRootTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='nami', email='nami@example.com', password='x')
        self.user.organization_memberships = {1: 'member'}
        self.space = Space.objects.create(
            organization_id=1, key='NAMIQA128', name='QA', owner_id=self.user.id, visibility='org',
        )
        self.page = Page.objects.create(
            space=self.space, title='fixture', position=0, created_by_id=self.user.id,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_reply_is_nested_once_and_not_a_list_root(self):
        root = self.client.post(
            f'/api/pages/{self.page.id}/comments/',
            {'content': 'root', 'parent': None},
            format='json',
        )
        reply = self.client.post(
            f'/api/pages/{self.page.id}/comments/',
            {'content': 'WIKI-128 isolated reply', 'parent': root.data['id']},
            format='json',
        )
        listed = self.client.get(f'/api/comments/?page_id={self.page.id}')
        self.assertEqual(listed.status_code, 200, listed.content)
        results = listed.data['results']
        self.assertEqual([row['id'] for row in results], [root.data['id']])
        self.assertEqual([row['id'] for row in results[0]['replies']], [reply.data['id']])

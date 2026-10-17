"""WIKI-53 regression: comment create -> get attribution -> update as the same
authenticated user must work (author persisted + editable), including a
threaded reply.

The live QA repro (2026-07-29): an authenticated MCP user creates a comment,
wiki_get_comment renders Author: Unknown, and wiki_update_comment 403s with
"Only the comment author can edit this comment". Root cause: the MCP comment
tools acted as the AGENT identity (as_user=False), so the creator was not
persisted as the author; and the serializer exposed only created_by_id while
the MCP rendered author_email/author_id -> "Unknown".

Fix: (1) MCP comment tools delegate to the user (as_user=has_user_context) so
the creator is the author and can edit; (2) the serializer exposes author_id so
the author renders instead of "Unknown".
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from wiki.models import Space, Page

User = get_user_model()


class Wiki53CommentOwnershipTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            username='mika', email='mika@example.com', password='x',
            is_staff=False,
        )
        self.user_a.organization_memberships = {1: 'member'}
        self.s1 = Space.objects.create(organization_id=1, key='ENG', name='Eng',
                                       owner_id=self.user_a.id, visibility='org')
        self.p1 = Page.objects.create(space=self.s1, title='A1', position=0,
                                      created_by_id=self.user_a.id)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user_a)

    def test_creator_can_edit_own_comment_and_author_is_persisted(self):
        resp = self.client.post(
            f'/api/pages/{self.p1.id}/comments/',
            {'content': 'threaded reply', 'parent': None},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        comment_id = resp.data['id']
        # Creator persisted as author, and the author surface is exposed.
        self.assertEqual(resp.data['created_by_id'], self.user_a.id)
        self.assertEqual(resp.data['author_id'], self.user_a.id)
        self.assertIn('author_id', resp.data)

        # Creator can update their own comment.
        upd = self.client.patch(
            f'/api/comments/{comment_id}/',
            {'content': 'edited'},
            format='json',
        )
        self.assertEqual(upd.status_code, 200, upd.content)
        self.assertEqual(upd.data['content'], 'edited')

    def test_threaded_reply_attribution_and_edit(self):
        # Top-level comment, then a threaded reply by the same user.
        top = self.client.post(
            f'/api/pages/{self.p1.id}/comments/',
            {'content': 'root', 'parent': None},
            format='json',
        )
        self.assertEqual(top.status_code, 201, top.content)
        reply = self.client.post(
            f'/api/pages/{self.p1.id}/comments/',
            {'content': 'PLAT-5377 threaded reply', 'parent': top.data['id']},
            format='json',
        )
        self.assertEqual(reply.status_code, 201, reply.content)
        self.assertEqual(str(reply.data['parent']), str(top.data['id']))
        self.assertEqual(reply.data['author_id'], self.user_a.id)

        upd = self.client.patch(
            f'/api/comments/{reply.data["id"]}/',
            {'content': 'edited reply'},
            format='json',
        )
        self.assertEqual(upd.status_code, 200, upd.content)

    def test_other_user_cannot_edit(self):
        resp = self.client.post(
            f'/api/pages/{self.p1.id}/comments/',
            {'content': 'mine'},
            format='json',
        )
        comment_id = resp.data['id']
        other = User.objects.create_user(
            username='other', email='other@example.com', password='x',
        )
        other.organization_memberships = {1: 'member'}
        client2 = APIClient()
        client2.force_authenticate(user=other)
        upd = client2.patch(
            f'/api/comments/{comment_id}/',
            {'content': 'hijack'},
            format='json',
        )
        self.assertEqual(upd.status_code, 403)

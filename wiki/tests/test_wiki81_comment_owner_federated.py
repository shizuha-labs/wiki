"""WIKI-81 regression: a FEDERATED user (agent token) can edit/delete their own
fresh comment.

Live QA failure (2026-08-26): an authenticated agent-token user (user_id 141)
creates a comment (created_by_id=141, author_id=141) but PATCH/DELETE of the
same comment with the same token returns 403 "Only the comment author can edit
this comment". The WIKI-53 fix (wiki#60) resolved attribution but not
ownership for the federated path.

Root cause: the deployed shizuha_auth can hand back a str user.id (JWT
user_id claim without int coercion) while created_by_id is an int
(IntegerField). `141 != "141"` wrongly denies the owner. The fix is a
type-safe same_user_id() comparison in the ownership checks.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from shizuha_auth import FederatedUser
from wiki.models import Space, Page, PageComment


class Wiki81FederatedCommentOwnerTests(TestCase):
    def setUp(self):
        # FederatedUser mirrors the live agent-token identity (user_id 141).
        self.agent = FederatedUser(
            user_id=141, email='nagi@shizuha.com', username='nagi',
            organization_memberships={1: 'member'},
        )
        self.s1 = Space.objects.create(
            organization_id=1, key='ENG', name='Eng',
            owner_id=141, visibility='org',
        )
        self.p1 = Page.objects.create(
            space=self.s1, title='A1', position=0, created_by_id=141,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.agent)

    def test_federated_creator_can_edit_and_delete_own_comment(self):
        resp = self.client.post(
            f'/api/pages/{self.p1.id}/comments/',
            {'content': 'federated comment', 'parent': None},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        comment_id = resp.data['id']
        self.assertEqual(resp.data['created_by_id'], 141)
        self.assertEqual(resp.data['author_id'], 141)

        # Same federated identity can update.
        upd = self.client.patch(
            f'/api/comments/{comment_id}/',
            {'content': 'edited by federated owner'},
            format='json',
        )
        self.assertEqual(upd.status_code, 200, upd.content)
        self.assertEqual(upd.data['content'], 'edited by federated owner')

        # Same federated identity can delete.
        dele = self.client.delete(f'/api/comments/{comment_id}/')
        self.assertEqual(dele.status_code, 204, dele.content)
        self.assertFalse(PageComment.objects.filter(pk=comment_id).exists())

    def test_federated_threaded_reply_ownership(self):
        top = self.client.post(
            f'/api/pages/{self.p1.id}/comments/',
            {'content': 'root', 'parent': None},
            format='json',
        )
        self.assertEqual(top.status_code, 201, top.content)
        reply = self.client.post(
            f'/api/pages/{self.p1.id}/comments/',
            {'content': 'reply', 'parent': top.data['id']},
            format='json',
        )
        self.assertEqual(reply.status_code, 201, reply.content)
        self.assertEqual(reply.data['author_id'], 141)
        upd = self.client.patch(
            f'/api/comments/{reply.data["id"]}/',
            {'content': 'edited reply'},
            format='json',
        )
        self.assertEqual(upd.status_code, 200, upd.content)

    def test_string_user_id_owner_can_edit_and_delete(self):
        # WIKI-81 root cause: the deployed shizuha_auth can hand back a str
        # user.id (JWT user_id claim without int coercion) while created_by_id
        # is an int IntegerField. `141 != "141"` wrongly 403s the owner.
        # same_user_id() coerces both sides.
        agent_str = FederatedUser(
            user_id='141', email='nagi@shizuha.com', username='nagi',
            organization_memberships={1: 'member'},
        )
        self.assertEqual(agent_str.id, 141)  # local FederatedUser coerces
        # Simulate the deployed auth by forcing a string id on the instance.
        agent_str.id = '141'
        agent_str.pk = '141'
        client = APIClient()
        client.force_authenticate(user=agent_str)

        resp = client.post(
            f'/api/pages/{self.p1.id}/comments/',
            {'content': 'string-id comment', 'parent': None},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        comment_id = resp.data['id']
        self.assertEqual(resp.data['created_by_id'], 141)

        upd = client.patch(
            f'/api/comments/{comment_id}/',
            {'content': 'edited by string-id owner'},
            format='json',
        )
        self.assertEqual(upd.status_code, 200, upd.content)
        self.assertEqual(upd.data['content'], 'edited by string-id owner')

        dele = client.delete(f'/api/comments/{comment_id}/')
        self.assertEqual(dele.status_code, 204, dele.content)

    def test_other_federated_user_cannot_edit(self):
        resp = self.client.post(
            f'/api/pages/{self.p1.id}/comments/',
            {'content': 'mine'},
            format='json',
        )
        comment_id = resp.data['id']
        other = FederatedUser(
            user_id=999, email='other@shizuha.com', username='other',
            organization_memberships={1: 'member'},
        )
        client2 = APIClient()
        client2.force_authenticate(user=other)
        upd = client2.patch(
            f'/api/comments/{comment_id}/',
            {'content': 'hijack'},
            format='json',
        )
        self.assertEqual(upd.status_code, 403)

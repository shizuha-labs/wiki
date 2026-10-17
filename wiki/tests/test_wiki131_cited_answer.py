"""WIKI-131: extractive cited answers, refuse-with-citations, permission filter."""
from django.db.models.signals import post_save
from rest_framework.test import APIClient, APITestCase

from wiki.authentication import FederatedUser
from wiki.cited_answer import CITED_ANSWER_RELEVANCE_FLOOR
from wiki.models import Page, Space
from wiki.signals import update_search_vector

ORG = 1


def _fed(user_id=101, org=ORG):
    return FederatedUser(
        user_id=user_id, email=f'u{user_id}@org{org}.example', username=f'u{user_id}',
        is_staff=False, is_superuser=False, enabled_services=['wiki'],
        organization_memberships={org: 'member'},
    )


class CitedAnswerTests(APITestCase):
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
        self.space = Space.objects.create(
            key='ENG', name='Engineering', organization_id=ORG, visibility='org',
            owner_id=self.user_id,
        )
        self.other = Space.objects.create(
            key='SEC', name='Secret', organization_id=99, visibility='private',
            owner_id=999,
        )

    def _page(self, space, title, content, slug):
        return Page.objects.create(
            space=space, title=title, slug=slug, content_text=content,
            status='published', created_by_id=self.user_id, version=3,
        )

    def test_question_over_500_chars_is_rejected(self):
        resp = self.client.post('/api/answer/', {'question': 'x' * 501}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_floor_constant_is_named(self):
        self.assertEqual(CITED_ANSWER_RELEVANCE_FLOOR, 0.5)

    def test_floor_pass_returns_extractive_answer_and_stable_citation(self):
        page = self._page(
            self.space, 'Rotate tokens',
            '# Rotate\n\nRotate the forgejo token before the lease expires.\n',
            'rotate-tokens',
        )
        resp = self.client.post('/api/answer/', {
            'question': 'how do I rotate the forgejo token',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.data['answer'])
        self.assertIn('forgejo token', resp.data['answer'].lower())
        citation = resp.data['citations'][0]
        self.assertEqual(citation['page_id'], str(page.id))
        self.assertEqual(citation['version'], 3)
        self.assertTrue(citation['section_hash'])
        self.assertLessEqual(len(citation['excerpt']), 400)
        self.assertNotIn('refusal', resp.data)

    def test_floor_refuse_keeps_best_citations(self):
        self._page(self.space, 'Unrelated', '# Notes\n\nBicycles have spokes.\n', 'notes')
        resp = self.client.post('/api/answer/', {
            'question': 'how do I rotate the forgejo token',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data['answer'])
        self.assertEqual(resp.data['refusal'], 'no_passage_clears_floor')
        self.assertGreaterEqual(len(resp.data['citations']), 1)

    def test_permission_filter_omits_unreadable_excerpt(self):
        secret = 'SECRET-EXCERPT-MUST-NOT-LEAK'
        self._page(
            self.other, 'Hidden rotate',
            f'# Hidden\n\n{secret} rotate the forgejo token here.\n',
            'hidden-rotate',
        )
        self._page(
            self.space, 'Public rotate',
            '# Rotate\n\nRotate the forgejo token in the public runbook.\n',
            'public-rotate',
        )
        resp = self.client.post('/api/answer/', {
            'question': 'rotate the forgejo token',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        blob = str(resp.data)
        self.assertNotIn(secret, blob)
        self.assertNotIn('Hidden rotate', blob)

    def test_anonymous_omits_verification_fields(self):
        public = Space.objects.create(
            key='PUB', name='Public', organization_id=ORG, visibility='public',
            owner_id=self.user_id,
        )
        self._page(public, 'Rotate tokens', '# Rotate\n\nRotate the forgejo token.\n', 'pub-rotate')
        anon = APIClient()
        resp = anon.post('/api/answer/', {'question': 'rotate the forgejo token'}, format='json')
        self.assertEqual(resp.status_code, 200)
        for citation in resp.data['citations']:
            self.assertNotIn('verified', citation)
            self.assertNotIn('verified_at', citation)

    def test_citation_order_is_rank_then_page_id(self):
        first = self._page(
            self.space, 'A',
            '# A\n\nRotate the forgejo token once.\n',
            'a-rotate',
        )
        second = self._page(
            self.space, 'B',
            '# B\n\nRotate the forgejo token twice.\n',
            'b-rotate',
        )
        resp = self.client.post('/api/answer/', {
            'question': 'rotate the forgejo token',
            'max_citations': 5,
        }, format='json')
        ids = [c['page_id'] for c in resp.data['citations']]
        self.assertEqual(ids, sorted(ids, key=lambda value: ( -resp.data['citations'][ids.index(value)]['rank'], value)))
        self.assertIn(str(first.id), ids)
        self.assertIn(str(second.id), ids)

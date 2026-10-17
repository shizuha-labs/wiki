"""WIKI-13 related-pages ranking."""
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from unittest.mock import patch
from rest_framework.test import APIClient, APITestCase

from wiki.models import Label, Page, PageLink, Space
from wiki.related import related_pages_for
from wiki.signals import update_search_vector

User = get_user_model()
PAGES_URL = '/api/pages/'


class RelatedPagesTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient(HTTP_X_ORGANIZATION_ID='1')
        self.user = User.objects.create_user(
            username='wiki13', email='wiki13@example.com', password='x',
            is_staff=True, is_superuser=True,
        )
        self.client.force_authenticate(user=self.user)
        self.space = Space.objects.create(
            organization_id=1, key='ENG', name='Engineering',
            visibility='org', owner_id=self.user.id,
        )
        self.label = Label.objects.create(organization_id=1, name='runtime')

    def _page(self, title, content='', status='published'):
        return Page.objects.create(
            space=self.space, title=title, content_text=content,
            content_json={}, status=status, created_by_id=self.user.id,
        )

    def test_related_pages_blends_labels_links_and_similarity(self):
        source = self._page('Runtime Fleet Tokens', 'Claude token pool rollout runtime fleet')
        source.labels.add(self.label)
        linked = self._page('Token Pool Runbook', 'How to rotate token pool safely')
        labelled = self._page('Runtime Debugging', 'Fleet debugging checklist')
        labelled.labels.add(self.label)
        similar = self._page('Claude Fleet Health', 'Claude token pool health and fleet rollout')
        unrelated = self._page('Catering Plan', 'Lunch menus and office snacks')
        draft = self._page('Draft Token Notes', 'Claude token pool draft', status='draft')
        PageLink.objects.create(source_page=source, target_page=linked)

        ranked = related_pages_for(source, limit=10)
        titles = [item['page'].title for item in ranked]

        self.assertEqual(titles[:3], ['Token Pool Runbook', 'Runtime Debugging', 'Claude Fleet Health'])
        self.assertNotIn(unrelated.title, titles)
        self.assertNotIn(draft.title, titles)
        self.assertIn('linked', ranked[0]['reasons'])
        self.assertIn('shared_labels', ranked[1]['reasons'])
        self.assertIn('similar_content', ranked[2]['reasons'])

    def test_related_endpoint_returns_scores_and_reasons(self):
        source = self._page('Agent Runtime', 'runtime fleet agents')
        target = self._page('Runtime Fleet', 'runtime fleet operations')
        PageLink.objects.create(source_page=source, target_page=target)

        resp = self.client.get(f'{PAGES_URL}{source.id}/related/?limit=5')

        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data[0]['id'], str(target.id))
        self.assertGreater(resp.data[0]['related_score'], 0)
        self.assertIn('linked', resp.data[0]['related_reasons'])

    def test_visible_pages_queryset_is_not_boolean_evaluated(self):
        source = self._page('Runtime Fleet Tokens', 'Claude token pool rollout runtime fleet')
        target = self._page('Runtime Fleet', 'runtime fleet operations')
        PageLink.objects.create(source_page=source, target_page=target)
        visible = Page.objects.filter(space=self.space)

        with patch.object(visible, '_fetch_all', side_effect=AssertionError('boolean evaluation forced full queryset')):
            ranked = related_pages_for(source, visible_pages=visible, limit=5)

        self.assertEqual([item['page'].id for item in ranked], [target.id])

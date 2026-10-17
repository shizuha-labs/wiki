"""WIKI-14 label cloud + per-label page listing."""
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from rest_framework.test import APIClient, APITestCase

from wiki.models import Label, Page, Space
from wiki.signals import update_search_vector

User = get_user_model()


class LabelBrowseTests(APITestCase):
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
            username='wiki14', email='wiki14@example.com', password='x',
            is_staff=True, is_superuser=True,
        )
        self.client.force_authenticate(user=self.user)
        self.space = Space.objects.create(
            organization_id=1, key='ENG', name='Engineering', visibility='org', owner_id=self.user.id,
        )
        self.other_space = Space.objects.create(
            organization_id=1, key='OPS', name='Operations', visibility='org', owner_id=self.user.id,
        )
        self.runtime = Label.objects.create(organization_id=1, name='runtime', color='#111111')
        self.ops = Label.objects.create(organization_id=1, name='ops', color='#222222')

    def _page(self, title, space=None, status='published', labels=()):
        page = Page.objects.create(
            space=space or self.space, title=title, content_text=title, content_json={},
            status=status, created_by_id=self.user.id,
        )
        page.labels.set(labels)
        return page

    def test_label_cloud_counts_published_pages_in_requested_space(self):
        self._page('Runtime A', labels=[self.runtime])
        self._page('Runtime B', labels=[self.runtime])
        self._page('Ops A', labels=[self.ops])
        self._page('Runtime Draft', status='draft', labels=[self.runtime])
        self._page('Runtime Other Space', space=self.other_space, labels=[self.runtime])

        resp = self.client.get('/api/labels/cloud/?space_key=ENG')

        self.assertEqual(resp.status_code, 200, resp.content)
        counts = {row['name']: row['pages_count'] for row in resp.data}
        self.assertEqual(counts['runtime'], 2)
        self.assertEqual(counts['ops'], 1)
        self.assertEqual([row['name'] for row in resp.data], ['runtime', 'ops'])

    def test_label_pages_endpoint_lists_only_published_visible_pages_for_label(self):
        keep = self._page('Keep Me', labels=[self.runtime])
        self._page('Draft Hidden', status='draft', labels=[self.runtime])
        self._page('Other Label', labels=[self.ops])

        resp = self.client.get(f'/api/labels/{self.runtime.id}/pages/')

        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual([row['id'] for row in rows], [str(keep.id)])

    def test_label_pages_endpoint_filters_selected_space(self):
        keep = self._page('Keep ENG', labels=[self.runtime])
        self._page('Other Space Hidden', space=self.other_space, labels=[self.runtime])

        resp = self.client.get(f'/api/labels/{self.runtime.id}/pages/?space_key=ENG')

        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual([row['id'] for row in rows], [str(keep.id)])
        self.assertEqual([row['space_key'] for row in rows], ['ENG'])

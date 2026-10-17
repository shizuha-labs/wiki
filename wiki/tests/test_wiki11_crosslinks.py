"""
WIKI-11: cross-link insert + validation.

- Saving a page resolves every [[...]] / id link and syncs the PageLink
  backlink index.
- Unresolvable targets are surfaced as a non-blocking `link_warnings` list
  (the save still succeeds).
- The insert helper produces a correctly-formatted [[page]] link.
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from wiki.models import Space, Page, PageLink
from wiki.links import format_page_link, sync_page_links, resolve_target

User = get_user_model()

PAGES_URL = '/api/pages/'


def _doc(text):
    return {'type': 'doc', 'content': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': text}]}
    ]}


class CrossLinkValidationTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The Postgres FTS search-vector post_save signal (to_tsvector) is
        # PG-only and orthogonal to cross-link logic; disconnect it so the
        # suite runs on any backend (it fires on every Page save otherwise).
        from django.db.models.signals import post_save
        from wiki.signals import update_search_vector
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        from django.db.models.signals import post_save
        from wiki.signals import update_search_vector
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        # X-Organization-ID scopes read/detail routes; staff bypasses the
        # per-org membership check (we don't seed SpaceMembership rows here).
        self.client = APIClient(HTTP_X_ORGANIZATION_ID='1')
        self.user = User.objects.create_user(
            username='ryo-wiki11', email='ryo-wiki11@example.com', password='x',
            is_staff=True, is_superuser=True,
        )
        self.client.force_authenticate(user=self.user)
        self.space = Space.objects.create(
            organization_id=1, key='ENG', name='Engineering',
            visibility='org', owner_id=self.user.id,
        )

    def _page(self, title, content_text='', content_json=None):
        return Page.objects.create(
            space=self.space, title=title, content_text=content_text,
            content_json=content_json or {}, created_by_id=self.user.id,
        )

    def _create_via_api(self, title, content_text='', content_json=None):
        return self.client.post(PAGES_URL, {
            'space': str(self.space.id), 'title': title,
            'content_text': content_text, 'content_json': content_json or {},
        }, format='json')

    # ── valid links resolve clean + populate the backlink index ──
    def test_valid_wikilink_resolves_clean_and_links(self):
        target = self._page('Target Page')
        resp = self._create_via_api('Source', content_text='see [[Target Page]] here')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data.get('link_warnings'), [])
        src = Page.objects.get(id=resp.data['id'])
        self.assertTrue(PageLink.objects.filter(source_page=src, target_page=target).exists())

    def test_wikilink_resolves_by_slug_and_alias(self):
        target = self._page('Design Doc')  # slug: design-doc
        resp = self._create_via_api('S2', content_text='[[design-doc]] and [[Design Doc|the design]]')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data.get('link_warnings'), [])
        src = Page.objects.get(id=resp.data['id'])
        # both forms resolve to the same target → exactly one PageLink
        self.assertEqual(PageLink.objects.filter(source_page=src, target_page=target).count(), 1)

    # ── dangling target → warning, but save still succeeds ──
    def test_dangling_wikilink_warns_but_saves(self):
        resp = self._create_via_api('Has Broken', content_text='[[Nonexistent Page]] oops')
        self.assertEqual(resp.status_code, 201, resp.content)  # save succeeded
        self.assertIn('Nonexistent Page', resp.data.get('link_warnings', []))
        src = Page.objects.get(id=resp.data['id'])
        self.assertEqual(PageLink.objects.filter(source_page=src).count(), 0)

    def test_mixed_valid_and_dangling(self):
        self._page('Good')
        resp = self._create_via_api('Mixed', content_text='[[Good]] and [[Bad]]')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data.get('link_warnings'), ['Bad'])

    # ── id link (UUID in a content_json href) resolves ──
    def test_id_link_resolves(self):
        target = self._page('By Id')
        cj = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [
            {'type': 'text', 'text': 'ref', 'marks': [
                {'type': 'link', 'attrs': {'href': f'/wiki/pages/{target.id}'}}
            ]}
        ]}]}
        resp = self._create_via_api('Refs By Id', content_json=cj)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data.get('link_warnings'), [])
        src = Page.objects.get(id=resp.data['id'])
        self.assertTrue(PageLink.objects.filter(source_page=src, target_page=target).exists())

    def test_external_url_not_treated_as_dangling(self):
        cj = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [
            {'type': 'text', 'text': 'ext', 'marks': [
                {'type': 'link', 'attrs': {'href': 'https://example.com/foo'}}
            ]}
        ]}]}
        resp = self._create_via_api('Has External', content_json=cj)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data.get('link_warnings'), [])

    def test_internal_page_path_resolves_nonpage_path_ignored(self):
        # WIKI-11 review P3: only the canonical /spaces/<key>/pages/<slug> path
        # is an internal link; an unrelated relative path (/users/...) is not
        # flagged as dangling.
        target = self._page('Pathful')  # slug: pathful, space ENG
        cj = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [
            {'type': 'text', 'text': 'a', 'marks': [
                {'type': 'link', 'attrs': {'href': f'/wiki/spaces/{self.space.key}/pages/{target.slug}'}}]},
            {'type': 'text', 'text': 'b', 'marks': [
                {'type': 'link', 'attrs': {'href': '/users/someone'}}]},
        ]}]}
        resp = self._create_via_api('PathLinks', content_json=cj)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data.get('link_warnings'), [])  # /users not flagged
        src = Page.objects.get(id=resp.data['id'])
        self.assertTrue(PageLink.objects.filter(source_page=src, target_page=target).exists())

    # ── update re-syncs links (stale removed, new dangling warned) ──
    def test_update_resyncs_links(self):
        a = self._page('Alpha')
        self._page('Beta')
        resp = self._create_via_api('Editing', content_text='[[Alpha]]')
        src_id = resp.data['id']
        src = Page.objects.get(id=src_id)
        self.assertEqual(PageLink.objects.filter(source_page=src).count(), 1)
        # update: drop Alpha, add Beta + a dangling one
        up = self.client.patch(f'{PAGES_URL}{src_id}/', {
            'content_text': '[[Beta]] and [[Ghost]]',
        }, format='json')
        self.assertEqual(up.status_code, 200, up.content)
        self.assertEqual(up.data.get('link_warnings'), ['Ghost'])
        targets = set(PageLink.objects.filter(source_page=src).values_list('target_page__title', flat=True))
        self.assertEqual(targets, {'Beta'})  # Alpha link removed, Beta added

    # ── insert helper format ──
    def test_format_page_link_helper(self):
        p = self._page('My Page')  # slug: my-page
        self.assertEqual(format_page_link(p), '[[my-page]]')
        self.assertEqual(format_page_link(p, alias='My Page'), '[[my-page|My Page]]')

    def test_link_markup_endpoint(self):
        p = self._page('Endpoint Page')
        resp = self.client.get(f'{PAGES_URL}{p.id}/link_markup/?alias=Click')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['markup'], f'[[{p.slug}|Click]]')

    def test_resolve_target_unit(self):
        t = self._page('Resolvable')
        self.assertEqual(resolve_target(self.space, 'Resolvable'), t)   # title
        self.assertEqual(resolve_target(self.space, 'resolvable'), t)   # slug/ci
        self.assertEqual(resolve_target(self.space, str(t.id)), t)      # id
        self.assertIsNone(resolve_target(self.space, 'nope'))

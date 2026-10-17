"""PLAT-8954: fail-closed shrink guard on the wiki persist paths.

The CON-429 v7 loss shape: a client (web editor or truncated tool arg)
submitted only the verdict block of an 18K design SoT; the server stored it
and §1–§10 were destroyed silently. Live repro basis (2026-09-18): the MCP
whole-page path stores 17.5K payloads intact and the multi-section splice
preserves sibling sections — so the v7 truncation came from a client path
submitting short content, which the server cannot distinguish from intent.

Guard pinned here: a save that would drop >50% of stored content (when
>= 2000 chars are stored) is REJECTED with a typed error unless the caller
explicitly passes ``confirm_shrink=true`` — on both the whole-page PATCH and
the section-splice POST.
"""
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from wiki.authentication import FederatedUser
from wiki.models import Page, Space

ORG = 1


def _fed(user_id=9901, org=ORG, role='member'):
    return FederatedUser(
        user_id=user_id,
        email=f'user{user_id}@org{org}.example',
        username=f'user{user_id}',
        is_staff=False,
        is_superuser=False,
        enabled_services=['wiki'],
        organization_memberships={org: role},
    )


def _client(user, org=ORG):
    c = APIClient(HTTP_X_ORGANIZATION_ID=str(org))
    c.force_authenticate(user=user)
    return c


def _big_body(n_chars=6000, tag='KEEP'):
    """A single-section doc of ~n_chars: one H1 heading + distinctive
    paragraph markers. Single-section is load-bearing for the section-splice
    guard test (replacing the only section replaces the whole doc), and the
    heading is required for list_markdown_sections to see any section at all.
    """
    paras = [f"# {tag} Shrink Guard Document\n\n"]
    i = 0
    total = len(paras[0])
    while total < n_chars:
        i += 1
        p = f"{tag}-MARKER-{i:03d}: Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. ENDMARK-{i:03d}.\n\n"
        paras.append(p)
        total += len(p)
    return "".join(paras)


@override_settings(USE_TZ=True)
class ShrinkGuardTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Detach the Postgres FTS trigger so page saves run on any DB backend
        # (same hermetic pattern as the other page-save test modules).
        from wiki.signals import update_search_vector
        try:
            from django.db.models.signals import post_save
            post_save.disconnect(update_search_vector, sender=Page)
            cls._fts_detached = True
        except Exception:
            cls._fts_detached = False

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, '_fts_detached', False):
            from wiki.signals import update_search_vector
            from django.db.models.signals import post_save
            post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.user = _fed()
        # owner_id / created_by_id are NOT NULL IntegerFields (CI postgres
        # enforces them; bare-int house pattern per test_wiki26/test_wiki21).
        self.space = Space.objects.create(
            name='ShrinkGuard', key='SHRG', organization_id=ORG, owner_id=20,
        )
        self.client = _client(self.user)
        self.page = Page.objects.create(
            space=self.space,
            title='shrink guard page',
            content_text=_big_body(),
            content_json={'type': 'doc', 'content': []},
            created_by_id=9901,
        )

    def _patch(self, payload):
        return self.client.patch(
            f'/api/pages/{self.page.id}/', payload, format='json',
        )

    def test_whole_page_dramatic_shrink_rejected_without_confirm(self):
        """The v7 shape: submitting a short verdict block over an 18K doc
        must fail closed with a typed confirm_shrink error — not store."""
        stored = len(self.page.content_text)
        resp = self._patch({
            'content_text': 'APPROVED verdict block only.',
            'content_json': {'type': 'doc', 'content': []},
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content[:300])
        self.assertIn('confirm_shrink', resp.json())
        # DRF detail normalizes scalars to strings — compare as int.
        self.assertEqual(int(resp.json().get('stored_chars')), stored)
        self.page.refresh_from_db()
        self.assertEqual(len(self.page.content_text), stored, 'nothing may be stored')
        self.assertIn('KEEP-MARKER-001', self.page.content_text)

    def test_whole_page_dramatic_shrink_allowed_with_confirm(self):
        resp = self._patch({
            'content_text': 'APPROVED verdict block only.',
            'content_json': {'type': 'doc', 'content': []},
            'confirm_shrink': True,
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content[:300])
        self.page.refresh_from_db()
        self.assertEqual(self.page.content_text, 'APPROVED verdict block only.')

    def test_normal_edit_unaffected(self):
        """Small edits (well under the shrink threshold) must save unchanged
        in behavior — the guard only arms on >50% drops of >= 2000 chars."""
        body = _big_body() + '\nAppended line.\n'
        resp = self._patch({'content_text': body})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content[:300])
        self.page.refresh_from_db()
        self.assertIn('Appended line.', self.page.content_text)

    def test_small_page_shrink_unaffected(self):
        """The guard does not fire below the 2000-char stored floor — small
        pages may be rewritten freely."""
        self.page.content_text = 'short page body'
        self.page.save()
        resp = self._patch({'content_text': 'tiny'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content[:300])
        self.page.refresh_from_db()
        self.assertEqual(self.page.content_text, 'tiny')

    def test_section_splice_dramatic_shrink_rejected(self):
        """Defense in depth: a section edit whose splice base lost the rest of
        the doc must fail closed, not store the section as the whole page."""
        from wiki.section_edit import list_markdown_sections
        sections = list_markdown_sections(self.page.content_text)
        self.assertTrue(sections)
        target = sections[0]
        resp = self.client.post(
            f'/api/pages/{self.page.id}/sections/',
            {
                'heading_or_anchor': target.anchor,
                'base_section_hash': target.section_hash,
                'content': 'REPLACED section body only.',
            },
            format='json',
        )
        # A single-section doc: replacing it replaces everything → the guard
        # must reject (the whole doc is the section here).
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content[:300])
        self.assertIn('confirm_shrink', resp.json())
        self.page.refresh_from_db()
        self.assertIn('KEEP-MARKER-001', self.page.content_text, 'doc must be intact')

"""WIKI-124: page verification state — schema defaults + auto-clear invariant."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from wiki.models import Page, Space


class SpacePriorityDefaultTests(TestCase):
    def test_priority_defaults_to_5(self):
        space = Space.objects.create(organization_id=1, key="TST", name="Test", owner_id=13)
        self.assertEqual(space.priority, 5)


class VerificationAutoClearTests(TestCase):
    def setUp(self):
        self.space = Space.objects.create(organization_id=1, key="TST", name="Test", owner_id=13)
        self.page = Page.objects.create(
            space=self.space, title="Ledger", created_by_id=13,
            content_text="# H\n\nbody",
            content_json={"type": "doc", "content": []},
        )
        # simulate a verified page
        self.page.verified_at = timezone.now()
        self.page.verified_by_id = 13
        self.page.verify_owner_id = 13
        self.page.save()

    def _re_fetch(self):
        return Page.objects.get(pk=self.page.pk)

    def test_unverified_default(self):
        fresh = Page.objects.create(space=self.space, title="Fresh", created_by_id=13, content_text="x")
        self.assertIsNone(fresh.verified_at)
        self.assertIsNone(fresh.verified_by_id)
        self.assertIsNone(fresh.verify_owner_id)

    def test_content_change_clears(self):
        page = self._re_fetch()
        kwargs = Page.verification_auto_clear_kwargs("new", page.content_json, page.content_text, page.content_json)
        self.assertEqual(set(kwargs), {"verified_at", "verified_by_id", "verify_owner_id"})
        for field, value in kwargs.items():
            setattr(page, field, value)
        page.save()
        cleared = self._re_fetch()
        self.assertIsNone(cleared.verified_at)
        self.assertIsNone(cleared.verified_by_id)
        self.assertIsNone(cleared.verify_owner_id)

    def test_byte_identical_write_preserves(self):
        page = self._re_fetch()
        kwargs = Page.verification_auto_clear_kwargs(page.content_text, page.content_json, page.content_text, page.content_json)
        self.assertEqual(kwargs, {})

    def test_title_only_edit_preserves(self):
        page = self._re_fetch()
        kwargs = Page.verification_auto_clear_kwargs(page.content_text, page.content_json, page.content_text, page.content_json)
        self.assertEqual(kwargs, {})

    def test_wiki93_json_shape_change_clears_even_with_same_markdown(self):
        page = self._re_fetch()
        reshaped = {"type": "doc", "content": [], "meta": {"source": "re-render"}}
        kwargs = Page.verification_auto_clear_kwargs(page.content_text, reshaped, page.content_text, page.content_json)
        self.assertEqual(set(kwargs), {"verified_at", "verified_by_id", "verify_owner_id"})

    def test_section_no_op_preserves_and_real_change_clears(self):
        """Section path shape: old-vs-new compare drives the same helper."""
        page = self._re_fetch()
        old_text, old_json = page.content_text, page.content_json
        spliced = old_text.replace("body", "body v2")
        kwargs = Page.verification_auto_clear_kwargs(spliced, old_json, old_text, old_json)
        self.assertNotEqual(kwargs, {})
        no_op = Page.verification_auto_clear_kwargs(old_text, old_json, old_text, old_json)
        self.assertEqual(no_op, {})

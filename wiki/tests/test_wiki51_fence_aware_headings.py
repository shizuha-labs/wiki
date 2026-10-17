"""WIKI-51: the section parser must not index `#` comment lines inside fenced
code blocks as Markdown headings.

The heading scanner is now a fence-aware state machine (both fence chars,
>3-char fences, info strings, <=3-space indentation, nested fences, and
unterminated fences at EOF). Every heading consumer converges on
``_iter_heading_matches``.
"""
from django.test import SimpleTestCase

from wiki.section_edit import list_markdown_sections, text_to_tiptap_json


class FenceAwareHeadingTests(SimpleTestCase):
    def _headings(self, text):
        return [s.heading for s in list_markdown_sections(text)]

    def test_backtick_fence_comment_is_not_a_heading(self):
        text = (
            '## Seam constraint 1\n'
            '```python\n'
            '# workflow_service.py:11457\n'
            'excluded = {}\n'
            '# tasks.py:7518\n'
            'terminal = set()\n'
            '```\n'
            '## Consequences\n'
        )
        headings = self._headings(text)
        self.assertNotIn('workflow_service.py:11457', headings)
        self.assertNotIn('tasks.py:7518', headings)
        self.assertEqual(headings, ['Seam constraint 1', 'Consequences'])

    def test_genuine_heading_after_closed_fence_is_still_detected(self):
        # Negative control: a real heading after the fence must not be lost.
        text = '```\n# not a heading\n```\n# Real Heading\n'
        self.assertEqual(self._headings(text), ['Real Heading'])

    def test_bare_hash_and_shebang_inside_fence_produce_no_section(self):
        text = '```\n#\n#!/bin/sh\necho hi\n```\n## After\n'
        self.assertEqual(self._headings(text), ['After'])

    def test_tilde_fence_comment_is_not_a_heading(self):
        text = '~~~\n# comment\ncode\n~~~\n## After\n'
        self.assertEqual(self._headings(text), ['After'])

    def test_longer_fence_and_info_string(self):
        text = '````python\n# comment\ncode\n````\n## After\n'
        self.assertEqual(self._headings(text), ['After'])

    def test_mismatched_length_close_does_not_close_fence(self):
        # A closing fence shorter than the opener does NOT close the block.
        text = '````\n# comment\n```\n## Still inside\n````\n## After\n'
        self.assertEqual(self._headings(text), ['After'])

    def test_indented_fence_up_to_three_spaces(self):
        text = '   ```\n   # comment\n   code\n   ```\n## After\n'
        self.assertEqual(self._headings(text), ['After'])

    def test_nested_different_char_fence(self):
        # A ``` block inside a ```` block: the inner # comment is still inside
        # the outer fence.
        text = (
            '````\n'
            '```python\n'
            '# inner comment\n'
            'code\n'
            '```\n'
            '````\n'
            '## After\n'
        )
        self.assertEqual(self._headings(text), ['After'])

    def test_unterminated_fence_at_eof_stays_in_fence(self):
        text = '```\n# comment\ncode\n'
        self.assertEqual(self._headings(text), [])

    def test_section_boundaries_are_not_truncated_at_fence(self):
        # A section containing a fence keeps its full extent (no truncation).
        text = (
            '## Section\n'
            'intro\n'
            '```\n'
            '# comment\n'
            'code\n'
            '```\n'
            'tail\n'
            '## Next\n'
        )
        sections = list_markdown_sections(text)
        self.assertEqual([s.heading for s in sections], ['Section', 'Next'])
        self.assertIn('tail', sections[0].content)
        self.assertNotIn('Next', sections[0].content)

    def test_tiptap_conversion_ignores_fenced_comments(self):
        text = (
            '## Heading\n'
            '```python\n'
            '# comment\n'
            'code\n'
            '```\n'
        )
        doc = text_to_tiptap_json(text)
        headings = [b for b in doc['content'] if b.get('type') == 'heading']
        self.assertEqual([h['attrs']['level'] for h in headings], [2])
        self.assertEqual(headings[0]['content'][0]['text'], 'Heading')

"""WIKI-99 component-2(a): markdown image syntax → TipTap image nodes.

The MCP write path is the canonical markdown entry for agent pages (ryo's
09-15 datum: raw-API content_text writes bypass conversion). Before this
change, `![alt](url)` fell through to the link parser and produced a literal
`!` + link text run — the published body never showed the image even after
the frontend gained the image renderer (renderSafeImageTag), the sanitize
`img` allowance, and the backend `/wiki/api/attachments/<id>/view/` route.

The conversion must mirror the frontend resolveSafeMediaSrc allow-list:
http(s) URLs and same-origin `/wiki/...` paths become image nodes; every
other scheme stays ordinary text (defense in depth behind the render-time
checks).
"""

import importlib
import os
import sys
import unittest
from pathlib import Path


MCP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MCP_DIR))
os.environ.setdefault('SHIZUHA_WIKI_URL', 'https://wiki.example.test')

wiki_server = importlib.import_module('wiki_server')


class MarkdownImageNodeTests(unittest.TestCase):
    def test_standalone_image_line_becomes_block_image_node(self):
        doc = wiki_server._text_to_tiptap_json(
            'Intro paragraph\n\n![architecture diagram](/wiki/api/attachments/abc/view/)\n\nOutro'
        )
        kinds = [node['type'] for node in doc['content']]
        self.assertEqual(kinds, ['paragraph', 'image', 'paragraph'])
        image = doc['content'][1]
        self.assertEqual(image['attrs']['src'], '/wiki/api/attachments/abc/view/')
        self.assertEqual(image['attrs']['alt'], 'architecture diagram')

    def test_image_with_title_round_trips_title_attr(self):
        doc = wiki_server._text_to_tiptap_json(
            '![logo](https://example.com/logo.png "Shizuha logo")'
        )
        self.assertEqual(len(doc['content']), 1)
        image = doc['content'][0]
        self.assertEqual(image['type'], 'image')
        self.assertEqual(image['attrs']['title'], 'Shizuha logo')
        self.assertEqual(image['attrs']['alt'], 'logo')

    def test_inline_image_splits_paragraph_into_block_sequence(self):
        doc = wiki_server._text_to_tiptap_json(
            'Before text ![shot](https://example.com/shot.png) after text'
        )
        kinds = [node['type'] for node in doc['content']]
        self.assertEqual(kinds, ['paragraph', 'image', 'paragraph'])
        self.assertEqual(
            doc['content'][0]['content'][0]['text'], 'Before text'
        )
        self.assertEqual(
            doc['content'][2]['content'][0]['text'], 'after text'
        )

    def test_unsafe_schemes_never_become_image_nodes(self):
        for src in (
            'javascript:alert(1)',
            'data:image/svg+xml;base64,AAAA',
            'vbscript:msgbox',
            '//evil.example.com/pixel.png',
            '/etc/passwd.png',
        ):
            doc = wiki_server._text_to_tiptap_json(f'![x]({src})')
            kinds = [node['type'] for node in doc['content']]
            self.assertNotIn('image', kinds, f'unsafe src must not become an image node: {src}')

    def test_javascript_src_stays_escaped_text(self):
        doc = wiki_server._text_to_tiptap_json('![x](javascript:alert(1))')
        # The unsafe image falls through to the link/text parser — no image
        # node, no href carrying the scheme into an <a> either.
        for node in doc['content']:
            for mark in node.get('content', [{}])[0].get('marks', []):
                self.assertNotEqual(
                    mark.get('attrs', {}).get('href', '').lower().startswith('javascript:'),
                    True,
                )

    def test_regular_links_are_untouched(self):
        doc = wiki_server._text_to_tiptap_json('See [the docs](https://example.com/docs) here')
        paragraph = doc['content'][0]
        link_nodes = [n for n in paragraph['content'] if any(
            m.get('type') == 'link' for m in n.get('marks', [])
        )]
        self.assertEqual(len(link_nodes), 1)
        self.assertEqual(link_nodes[0]['text'], 'the docs')

    def test_wiki93_regression_markdown_features_unchanged(self):
        """WIKI-93: markdown vs content_json — existing conversions must not shift."""
        doc = wiki_server._text_to_tiptap_json(
            '# Title\n\n```mermaid\nflowchart TD\nA-->B\n```\n\n- item one\n- item two\n'
        )
        kinds = [node['type'] for node in doc['content']]
        self.assertEqual(kinds, ['heading', 'codeBlock', 'bulletList'])
        self.assertEqual(doc['content'][0]['attrs']['level'], 1)
        self.assertEqual(doc['content'][1]['attrs']['language'], 'mermaid')
        self.assertEqual(len(doc['content'][2]['content']), 2)

    def test_attachment_view_url_is_the_documented_agent_pattern(self):
        """Task Do-3: agents reference uploads as ![alt](/wiki/api/attachments/<id>/view/)."""
        markdown = '![diagram](/wiki/api/attachments/b5b5c3c7-1234-5678-9abc-def012345678/view/)'
        doc = wiki_server._text_to_tiptap_json(markdown)
        image = doc['content'][0]
        self.assertEqual(image['type'], 'image')
        self.assertEqual(
            image['attrs']['src'],
            '/wiki/api/attachments/b5b5c3c7-1234-5678-9abc-def012345678/view/',
        )


if __name__ == '__main__':
    unittest.main()

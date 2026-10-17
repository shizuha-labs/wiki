import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import MarkdownIt from 'markdown-it'

import { attachmentIdFromMediaSrc, shouldRenderMarkdown } from '../src/utils/pageContent.js'

assert.equal(
  attachmentIdFromMediaSrc('/wiki/api/attachments/1b97f188-dc78-4084-a392-22780dcf66e9/view/'),
  '1b97f188-dc78-4084-a392-22780dcf66e9',
)
assert.equal(attachmentIdFromMediaSrc('https://example.com/photo.jpg'), null)

const fixture = `# Weekly plan

**Owner:** Jun and *status:* won.

[Research Pack](2bf8d7c5-ddb1-4443-b021-534f55d82ae0)

| Day | Slot allocation |
| --- | --- |
| 1 | Observe |
| 2 | Iterate |

- preserve lists
- render **bold** inside list items

Use \`pulse_get_task\` but preserve the literal **markers** inside fenced code:

\`\`\`markdown
**not bold** | not a table |
\`\`\``

const markdown = new MarkdownIt({ html: false, linkify: false, typographer: false })
const tokens = markdown.parse(fixture, {})
const tokenTypes = new Set(tokens.map((token) => token.type))
const inlineChildren = tokens
  .filter((token) => token.type === 'inline')
  .flatMap((token) => token.children || [])
const inlineTypes = new Set(inlineChildren.map((token) => token.type))

for (const type of ['heading_open', 'table_open', 'bullet_list_open', 'fence']) {
  assert.equal(tokenTypes.has(type), true, `${type} must be parsed semantically`)
}
for (const type of ['strong_open', 'em_open', 'link_open', 'code_inline']) {
  assert.equal(inlineTypes.has(type), true, `${type} must be parsed semantically`)
}
assert.match(tokens.find((token) => token.type === 'fence')?.content || '', /\*\*not bold\*\*/)
assert.equal(
  inlineChildren.find((token) => token.type === 'link_open')?.attrGet('href'),
  '2bf8d7c5-ddb1-4443-b021-534f55d82ae0',
)

const rendererSource = await readFile(
  fileURLToPath(new URL('../src/utils/pageContent.js', import.meta.url)),
  'utf8',
)
const pageViewSource = await readFile(
  fileURLToPath(new URL('../src/pages/PageView.jsx', import.meta.url)),
  'utf8',
)

assert.match(rendererSource, /new MarkdownIt\(\{[\s\S]*html: false/)
assert.match(rendererSource, /DOMPurify\.sanitize\(html/)
assert.match(rendererSource, /SAFE_LINK_PROTOCOLS\.has\(url\.protocol\)/)
assert.match(rendererSource, /UUID_LINK\.test\(value\)[\s\S]*`\/wiki\/pages\//)
assert.match(rendererSource, /ALLOWED_TAGS:[\s\S]*'code'[\s\S]*'table'/)
assert.match(rendererSource, /ALLOWED_ATTR: \['class', 'href', 'id', 'rel', 'target', 'src', 'alt', 'title', 'width', 'height'\]/)
assert.match(rendererSource, /ALLOWED_TAGS:[\s\S]*'img'[\s\S]*'div'|ALLOWED_TAGS:[\s\S]*'div'[\s\S]*'img'/)
assert.match(rendererSource, /FORBID_TAGS: \['svg'/)
assert.match(rendererSource, /wiki-mermaid/)
assert.match(rendererSource, /markdownHeadings\(contentText\)/)
assert.match(rendererSource, /renderTableOfContents\(headings\)/)
assert.match(rendererSource, /token\.attrSet\('id', `heading-\$\{headingIndex\+\+\}`\)/)
assert.match(pageViewSource, /shouldRenderMarkdown\(page\.content_json, page\.content_text\)/)
assert.match(pageViewSource, /renderMarkdownContent\(page\.content_text\)/)
assert.match(pageViewSource, /sanitizePageContent\(renderNode\(contentJson\)\)/)

// WIKI-93 regression: mixed persistence (real heading nodes + Markdown persisted
// literally in paragraph/list text nodes — the MCP/section-update fallback) must
// route to the Markdown renderer. The strict projection equality dropped these
// pages into the rich-text path, rendering the literal Markdown raw (114 visible
// '**' sequences, pipe tables as text) on the live gen-17 page.
const mixedJson = {
  type: 'doc',
  content: [
    {
      type: 'heading',
      attrs: { level: 1 },
      content: [{ type: 'text', text: 'Playbook: 14-Day Adaptive Growth Plan' }],
    },
    {
      type: 'paragraph',
      content: [{ type: 'text', text: '**Pulse:** SM-9 · **Owner:** Nori / Social Media' }],
    },
    {
      type: 'heading',
      attrs: { level: 2 },
      content: [{ type: 'text', text: 'Hook bank' }],
    },
    {
      type: 'paragraph',
      content: [{
        type: 'text',
        text: '- We gave multiple agents one company to run.\n- The **invisible handoff** is the failure.\n\n| Day | Slot |\n|---|---|\n| 1 | Observe |\n\nUse `pulse_get_task` and see [the pack](2bf8d7c5-ddb1-4443-b021-534f55d82ae0).',
      }],
    },
  ],
}
const mixedText = [
  '# Playbook: 14-Day Adaptive Growth Plan',
  '',
  '**Pulse:** SM-9 · **Owner:** Nori / Social Media',
  '',
  '## Hook bank',
  '',
  '- We gave multiple agents one company to run.',
  '- The **invisible handoff** is the failure.',
  '',
  '| Day | Slot |',
  '|---|---|',
  '| 1 | Observe |',
  '',
  'Use `pulse_get_task` and see [the pack](2bf8d7c5-ddb1-4443-b021-534f55d82ae0).',
].join('\n')
assert.equal(
  shouldRenderMarkdown(mixedJson, mixedText), true,
  'mixed persistence (real headings + literal-Markdown bodies) must route to the Markdown renderer',
)

// PLAT-10013: mixed persistence where inline marks diverge (bold/links became
// node attrs, so the projection no longer carries ** and []()) — the WIKI-93
// equality fails, but the literal ``` fences in paragraph text are decisive
// Markdown-persistence evidence and must route to the Markdown renderer so
// ```mermaid fences hydrate instead of rendering raw.
const mixedFenceJson = {
  type: 'doc',
  content: [
    {
      type: 'heading',
      attrs: { level: 2 },
      content: [{ type: 'text', text: 'Context diagram' }],
    },
    {
      type: 'paragraph',
      content: [{
        type: 'text',
        text: '```mermaid\nflowchart LR\n  a["A"] --> b["B"]\n```',
      }],
    },
    {
      type: 'paragraph',
      content: [
        { type: 'text', marks: [{ type: 'bold' }], text: 'Status:' },
        { type: 'text', text: ' shipped, see ' },
        { type: 'text', marks: [{ type: 'link', attrs: { href: '/wiki/spaces/ENG/pages/x' } }], text: 'the runbook' },
        { type: 'text', text: '.' },
      ],
    },
  ],
}
const mixedFenceText = [
  '## Context diagram',
  '',
  '```mermaid',
  'flowchart LR',
  '  a["A"] --> b["B"]',
  '```',
  '',
  '**Status:** shipped, see [the runbook](/wiki/spaces/ENG/pages/x).',
].join('\n')
assert.equal(
  shouldRenderMarkdown(mixedFenceJson, mixedFenceText), true,
  'mixed persistence with mark-divergent projection + literal fences must route to Markdown (PLAT-10013)',
)

// Genuine TipTap rich text keeps the rich path: the projection has marks applied
// (no literal '**') while content_text carries the Markdown wrappers, which the
// block-marker strip does not touch.
const richJson = {
  type: 'doc',
  content: [
    {
      type: 'heading',
      attrs: { level: 1 },
      content: [{ type: 'text', text: 'Weekly plan' }],
    },
    {
      type: 'paragraph',
      content: [
        { type: 'text', marks: [{ type: 'bold' }], text: 'Owner:' },
        { type: 'text', text: ' Jun and ' },
        { type: 'text', marks: [{ type: 'italic' }], text: 'status' },
        { type: 'text', text: ' won.' },
      ],
    },
  ],
}
const richText = ['# Weekly plan', '', '**Owner:** Jun and *status* won.'].join('\n')
assert.equal(
  shouldRenderMarkdown(richJson, richText), false,
  'genuine rich text (marks applied) must stay on the rich-text path',
)

// A genuine codeBlock node stores only its code content (no ``` markers), so a
// rich-text page with a mermaid codeBlock must NOT trip the fence classifier
// and must stay on the rich-text path (PLAT-10013 guard).
const richCodeBlockJson = {
  type: 'doc',
  content: [
    {
      type: 'codeBlock',
      attrs: { language: 'mermaid' },
      content: [{ type: 'text', text: 'flowchart LR\n  a["A"] --> b["B"]' }],
    },
    {
      type: 'paragraph',
      content: [
        { type: 'text', marks: [{ type: 'bold' }], text: 'Diagram above.' },
      ],
    },
  ],
}
const richCodeBlockText = [
  '```mermaid',
  'flowchart LR',
  '  a["A"] --> b["B"]',
  '```',
  '',
  '**Diagram above.**',
].join('\n')
assert.equal(
  shouldRenderMarkdown(richCodeBlockJson, richCodeBlockText), false,
  'rich text with a real codeBlock node must stay on the rich-text path (no literal fences in projection)',
)

// Boundary behaviors preserved.
assert.equal(shouldRenderMarkdown(null, 'text with **bold**'), true, 'missing content_json -> Markdown source')
assert.equal(shouldRenderMarkdown(mixedJson, ''), false, 'empty content_text -> not Markdown source')

console.log(JSON.stringify({
  pageContentRenderingRegression: 'passed',
  constructs: ['heading', 'bold', 'emphasis', 'internal-link', 'table', 'list', 'inline-code', 'fenced-code'],
  xssBoundary: ['markdown-html-disabled', 'DOMPurify-allowlist', 'safe-link-protocols', 'legacy-json-sanitized'],
  wiki93: ['mixed-persistence-routes-to-markdown', 'genuine-rich-text-stays-rich', 'boundary-behaviors-preserved'],
}))

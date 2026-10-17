// WIKI-120 acceptance 3 — regression coverage for the editor save path.
//
// The editor save paths used to persist `content_text: editor.getText()`,
// which flattens structured pages (heading markers live in TipTap node
// attributes; fence delimiters in the node type). ADR-0056 was flattened
// exactly this way. These checks pin the replacement serializer
// (`docToMarkdown`) to the acceptance contract:
//
//   1. Round-trip a fenced document with `#` comment lines through the
//      serializer: every heading marker survives, fence content is
//      byte-verbatim (including `#` comment lines), and the section index
//      implied by the emitted markdown matches the source document.
//   2. Negative case: a paragraph carrying an unterminated fence opener
//      is emitted verbatim and never swallows following content.
//   3. The old flattening behavior must NOT recur: serialized output of a
//      heading-bearing doc differs from the getText()-style flattening.

import assert from 'node:assert/strict'

import { docToMarkdown } from '../src/utils/pageContent.js'

// -- 1. Round-trip fidelity --------------------------------------------------

const sourceDoc = {
  type: 'doc',
  content: [
    {
      type: 'heading',
      attrs: { level: 1 },
      content: [{ type: 'text', text: 'ADR-0056: contract' }],
    },
    {
      type: 'heading',
      attrs: { level: 2 },
      content: [{ type: 'text', text: 'Seam constraint 1' }],
    },
    {
      type: 'paragraph',
      content: [{ type: 'text', text: 'The two lines below are load-bearing.' }],
    },
    {
      type: 'codeBlock',
      attrs: { language: 'python' },
      content: [
        {
          type: 'text',
          text: '# workflow_service.py:11457\nwait = ExternalWait.objects.get(pk=ref)\n# tasks.py:7518\napply(wait)',
        },
      ],
    },
    {
      type: 'heading',
      attrs: { level: 2 },
      content: [{ type: 'text', text: 'Decision' }],
    },
    {
      type: 'paragraph',
      content: [{ type: 'text', text: 'Plain exclusion now.' }],
    },
  ],
}

const md = docToMarkdown(sourceDoc)

// Every heading marker survives, at the right level.
assert.ok(md.includes('# ADR-0056: contract\n'), 'H1 marker missing')
assert.ok(md.includes('## Seam constraint 1\n'), 'H2 marker missing')
assert.ok(md.includes('## Decision\n'), 'second H2 marker missing')

// Fence content byte-verbatim, including `#` comment lines and the fence
// delimiters themselves.
const fenceBlock = [
  '```python',
  '# workflow_service.py:11457',
  'wait = ExternalWait.objects.get(pk=ref)',
  '# tasks.py:7518',
  'apply(wait)',
  '```',
].join('\n')
assert.ok(md.includes(fenceBlock), `fence block not byte-verbatim:\n${md}`)

// Section index implied by the output matches the source document.
// Fence-aware extraction (mirrors the server's WIKI-51 tracker): lines inside
// ``` fences are code, never headings.
let inFence = false
const sectionTitles = []
for (const line of md.split('\n')) {
  if (/^\s*(```|~~~)/.test(line)) {
    inFence = !inFence
    continue
  }
  if (!inFence && /^#{1,6} /.test(line)) {
    sectionTitles.push(line.replace(/^#+ /, ''))
  }
}
assert.deepEqual(
  sectionTitles,
  ['ADR-0056: contract', 'Seam constraint 1', 'Decision'],
  'section index diverged',
)

// Unfenced `#` comment lines never lose their marker: a code block is the
// only place `#` appears verbatim, and headings outside fences keep theirs.
assert.ok(!/^workflow_service\.py:11457$/m.test(md), 'in-fence comment was stripped')

// -- 2. Negative case: unterminated fence opener in a paragraph --------------

const unterminated = docToMarkdown({
  type: 'doc',
  content: [
    {
      type: 'paragraph',
      content: [{ type: 'text', text: 'stray opener: ```python' }],
    },
    {
      type: 'paragraph',
      content: [{ type: 'text', text: 'still a paragraph, not swallowed' }],
    },
  ],
})
assert.ok(unterminated.includes('```python'), 'stray opener dropped')
assert.ok(
  unterminated.includes('still a paragraph, not swallowed'),
  'content after unterminated opener was swallowed',
)

// Degenerate inputs never crash.
assert.equal(docToMarkdown(null), '')
assert.equal(docToMarkdown({ type: 'doc' }), '')
assert.equal(docToMarkdown({ type: 'doc', content: [] }), '\n'.length === 1 ? '\n' : '')

// -- 3. The old flattening must not recur ------------------------------------

// getText()-style flattening would emit `ADR-0056: contract` with no marker.
assert.ok(!/^ADR-0056: contract$/m.test(md), 'heading marker was stripped (getText() regression)')

console.log('wiki120 editor markdown serialization: OK')

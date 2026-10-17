import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import MarkdownIt from 'markdown-it'

const mode = process.argv[2]

if (mode === '--worker') {
  const vulnerability = process.argv[3]
  const markdown = new MarkdownIt()

  // Wiki's pageContent renderer consumes markdown-it directly. TipTap 3 no
  // longer exports the old ProseMirror markdown wrapper.
  // Enable both optional rules here so the regression covers the vulnerable
  // markdown-rendering boundary even when a caller opts into either feature.
  markdown.enable(['linkify', 'smartquotes'])
  markdown.set({ linkify: true, typographer: true })

  let payload
  if (vulnerability === 'linkify') {
    payload = `https://test.com?${'*'.repeat(70_000)}a`
  } else if (vulnerability === 'smartquotes') {
    payload = '"'.repeat(160_000)
  } else {
    throw new Error(`unknown markdown security regression: ${vulnerability}`)
  }

  const startedAt = performance.now()
  const tokens = markdown.parse(payload, {})
  const elapsedMs = performance.now() - startedAt

  const inline = tokens.flatMap(token => token.children || [])
  const linkMarks = inline.filter(token => token.type === 'link_open').length
  const textContent = inline.filter(token => token.type === 'text').map(token => token.content).join('')

  process.stdout.write(JSON.stringify({
    vulnerability,
    elapsedMs,
    textLength: textContent.length,
    firstCharacters: textContent.slice(0, 4),
    linkMarks,
  }))
  process.exit(0)
}

const scriptPath = fileURLToPath(import.meta.url)
const results = {}

for (const vulnerability of ['linkify', 'smartquotes']) {
  // Keep pathological parsing out of the test process so a vulnerable lock
  // is killed deterministically instead of consuming CI indefinitely.
  const output = execFileSync(
    process.execPath,
    [scriptPath, '--worker', vulnerability],
    { encoding: 'utf8', timeout: 3_000 },
  )
  const result = JSON.parse(output)

  assert.ok(
    result.elapsedMs < 2_000,
    `${vulnerability} payload took ${result.elapsedMs.toFixed(1)}ms`,
  )
  results[vulnerability] = result
}

assert.equal(results.linkify.textLength, 70_018)
assert.equal(results.linkify.linkMarks, 1)
assert.equal(results.smartquotes.textLength, 160_000)
assert.equal(results.smartquotes.firstCharacters, '“”“”')

console.log(JSON.stringify({
  markdownRenderingSecurityRegression: 'passed',
  linkifyElapsedMs: Number(results.linkify.elapsedMs.toFixed(1)),
  smartquotesElapsedMs: Number(results.smartquotes.elapsedMs.toFixed(1)),
}))

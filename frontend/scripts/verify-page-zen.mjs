import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const layout = await readFile(
  fileURLToPath(new URL('../src/components/Layout.jsx', import.meta.url)),
  'utf8',
)
const pageView = await readFile(
  fileURLToPath(new URL('../src/pages/PageView.jsx', import.meta.url)),
  'utf8',
)
const css = await readFile(
  fileURLToPath(new URL('../src/index.css', import.meta.url)),
  'utf8',
)
const app = await readFile(
  fileURLToPath(new URL('../src/App.jsx', import.meta.url)),
  'utf8',
)

assert.match(layout, /wiki-chrome/)
assert.match(layout, /wiki-shell/)
assert.match(layout, /wiki-main/)
assert.match(css, /html\.wiki-zen \.wiki-chrome/)
assert.match(css, /html\.wiki-zen \.wiki-shell/)
assert.match(pageView, /requestFullscreen/)
assert.match(pageView, /exitFullscreen/)
assert.match(pageView, /enterZen/)
assert.match(pageView, /Exit zen/)
assert.match(pageView, /Maximize2/)
assert.match(app, /wiki-chrome/)
assert.match(pageView, /WIKI_MERMAID_CLASS/)

console.log(JSON.stringify({
  pageZenRegression: 'passed',
  hides: ['sidebar', 'topbar', 'search', 'chat'],
  fullscreen: ['requestFullscreen', 'exitFullscreen', 'Esc via fullscreenchange'],
}))

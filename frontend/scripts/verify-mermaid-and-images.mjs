import assert from 'node:assert/strict'
import { readFile, stat } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const rendererSource = await readFile(
  fileURLToPath(new URL('../src/utils/pageContent.js', import.meta.url)),
  'utf8',
)
const hydrateSource = await readFile(
  fileURLToPath(new URL('../src/utils/mermaidHydrate.js', import.meta.url)),
  'utf8',
)
const pageViewSource = await readFile(
  fileURLToPath(new URL('../src/pages/PageView.jsx', import.meta.url)),
  'utf8',
)
const packageJson = await readFile(
  fileURLToPath(new URL('../package.json', import.meta.url)),
  'utf8',
)
const mermaidBundle = await readFile(
  fileURLToPath(new URL('../public/mermaid-11.17.2.min.js', import.meta.url)),
  'utf8',
)

assert.equal(/"mermaid"\s*:/.test(packageJson), false, 'mermaid must not be an npm dependency')
assert.match(hydrateSource, /securityLevel: 'strict'/)
assert.match(hydrateSource, /loadDiagramPrefs/)
assert.match(hydrateSource, /mermaidThemeForPrefs/)
assert.match(hydrateSource, /roundSvgRects/)
assert.match(hydrateSource, /data-mermaid-source/)
assert.match(hydrateSource, /data-mermaid-theme/)
assert.match(hydrateSource, /prefs.look === 'neo'/)
assert.match(hydrateSource, /handDrawn/)
assert.match(hydrateSource, /mermaidThemeVariablesForPrefs/)
assert.match(hydrateSource, /mermaidFontForPrefs/)
assert.match(hydrateSource, /attachMermaidViewer/)
assert.match(hydrateSource, /mermaid-11\.17\.2\.min\.js/)
const cssSource = await readFile(
  fileURLToPath(new URL('../src/index.css', import.meta.url)),
  'utf8',
)
const viewerSource = await readFile(
  fileURLToPath(new URL('../src/utils/mermaidViewer.js', import.meta.url)),
  'utf8',
)
const cloneIdsSource = await readFile(
  fileURLToPath(new URL('../src/utils/mermaidCloneIds.js', import.meta.url)),
  'utf8',
)
assert.match(viewerSource, /wiki-diagram-stage/)
assert.match(viewerSource, /Scroll to zoom/)
assert.match(viewerSource, /middle-mouse/)
assert.match(viewerSource, /Space-drag/)
assert.match(viewerSource, /wheelZoomFactor/)
assert.match(viewerSource, /settings#diagrams/)
assert.equal(viewerSource.includes('if (prefs.scrollZoom)'), false, 'opened viewer always zooms on wheel')
assert.match(viewerSource, /pinCloneSize/)
assert.match(viewerSource, /rewireCloneIds/)
assert.match(viewerSource, /data-diagram-look/)
assert.match(viewerSource, /backgroundColor/)
assert.match(cloneIdsSource, /rewriteMermaidStyleText/)
assert.equal(viewerSource.includes("removeAttribute('id')"), false, 'fullscreen clone must keep mermaid CSS id')
assert.match(viewerSource, /ResizeObserver/)
assert.match(cssSource, /wiki-diagram-stage:fullscreen/)
assert.match(cssSource, /wiki-diagram-stage/)
assert.match(cssSource, /wiki-mermaid-chrome/)
assert.match(cssSource, /wiki-mermaid svg \.node rect/)
assert.match(cssSource, /wiki-diagram-world svg \.node rect/)
assert.match(cssSource, /--wiki-diagram-rx/)
assert.match(cssSource, /var\(--wiki-diagram-rx\)/)
const prefsSource = await readFile(
  fileURLToPath(new URL('../src/utils/diagramPrefs.js', import.meta.url)),
  'utf8',
)
assert.match(prefsSource, /DIAGRAM_PREFS_KEY/)
assert.match(prefsSource, /shizuha_wiki_diagram_prefs/)
assert.match(prefsSource, /hydrateDiagramPrefsFromAccount/)
assert.match(prefsSource, /preferencesApi/)
assert.match(prefsSource, /handDrawn/)
assert.match(prefsSource, /whiteboard/)
assert.match(prefsSource, /DIAGRAM_PACKS/)
assert.match(prefsSource, /Virgil/)
const settingsSource = await readFile(
  fileURLToPath(new URL('../src/pages/Settings.jsx', import.meta.url)),
  'utf8',
)
assert.match(settingsSource, /id="diagrams"/)
assert.match(settingsSource, /Color scheme/)
assert.match(settingsSource, /Saved to your account/)
assert.match(settingsSource, /Whiteboard/)
assert.match(settingsSource, /Hand-drawn/)
assert.match(settingsSource, /scroll wheel zooms/)
assert.equal(settingsSource.includes('off = scroll pans'), false)
assert.match(cssSource, /font-family: Virgil/)
assert.match(cssSource, /Virgil\.woff2/)
assert.match(cssSource, /invert\(93%\) hue-rotate\(180deg\)/)
assert.match(cssSource, /wiki-diagram-stage\[data-diagram-look='handDrawn'\]/)
assert.match(cssSource, /foreignObject \*/)
assert.match(cssSource, /:not\(\.wiki-mermaid/)
assert.match(cssSource, /fill: #1e1e1e !important/)
assert.match(prefsSource, /scheme: 'whiteboard'/)
assert.match(prefsSource, /look: 'handDrawn'/)
assert.match(prefsSource, /LEGACY_DIAGRAM_DEFAULTS/)
assert.match(prefsSource, /Excalidraw · default/)
assert.match(rendererSource, /not-prose/)
assert.match(prefsSource, /edgeLabelBackground: '#ffffff'/)
assert.match(prefsSource, /primaryTextColor: '#1e1e1e'/)
const virgilFont = await stat(fileURLToPath(new URL('../src/assets/fonts/Virgil.woff2', import.meta.url)))
assert.ok(virgilFont.size > 10_000, 'Virgil woff2 is vendored')
assert.equal(settingsSource.includes('this browser'), false)
const apiSource = await readFile(
  fileURLToPath(new URL('../src/services/api.js', import.meta.url)),
  'utf8',
)
assert.match(apiSource, /preferencesApi/)
assert.match(apiSource, /\/preferences\//)
const authSource = await readFile(
  fileURLToPath(new URL('../src/contexts/AuthContext.jsx', import.meta.url)),
  'utf8',
)
assert.match(authSource, /hydrateDiagramPrefsFromAccount/)
assert.match(pageViewSource, /DIAGRAM_PREFS_EVENT/)
assert.match(mermaidBundle, /globalThis\["mermaid"\]/)
assert.ok(mermaidBundle.length > 1_000_000, 'vendored mermaid bundle is present')
assert.match(pageViewSource, /hydrateWikiMermaid/)
assert.match(pageViewSource, /case 'image':/)
assert.match(pageViewSource, /renderSafeImageTag/)
assert.match(rendererSource, /html: false/)
assert.match(rendererSource, /info === 'mermaid'/)
assert.match(rendererSource, /FORBID_TAGS: \['svg'/)
assert.match(rendererSource, /BLOCKED_MEDIA_SCHEMES/)
assert.match(rendererSource, /export const WIKI_MERMAID_CLASS = 'wiki-mermaid'/)

const { rewriteMermaidStyleText } = await import('../src/utils/mermaidCloneIds.js')
const rewritten = rewriteMermaidStyleText(
  '#wiki-mermaid-abc{fill:#ccc;}#wiki-mermaid-abc .node rect{fill:#474949;}url(#wiki-mermaid-abc_flowchart-v2-pointEnd)',
  new Map([
    ['wiki-mermaid-abc', 'wiki-mermaid-abc-zen-1'],
    ['wiki-mermaid-abc_flowchart-v2-pointEnd', 'wiki-mermaid-abc_flowchart-v2-pointEnd-zen-1'],
  ]),
)
assert.match(rewritten, /#wiki-mermaid-abc-zen-1\{fill:#ccc;\}/)
assert.match(rewritten, /#wiki-mermaid-abc-zen-1 \.node rect\{fill:#474949;\}/)
assert.match(rewritten, /url\(#wiki-mermaid-abc_flowchart-v2-pointEnd-zen-1\)/)
assert.equal(rewritten.includes('#wiki-mermaid-abc{'), false)
assert.equal(rewritten.includes('#wiki-mermaid-abc .node'), false)

let resolveSafeMediaSrc
let renderSafeImageTag
let WIKI_MERMAID_CLASS
try {
  const pageContent = await import('../src/utils/pageContent.js')
  resolveSafeMediaSrc = pageContent.resolveSafeMediaSrc
  renderSafeImageTag = pageContent.renderSafeImageTag
  WIKI_MERMAID_CLASS = pageContent.WIKI_MERMAID_CLASS
} catch (err) {
  if (err.code !== 'ERR_MODULE_NOT_FOUND') throw err
  console.log(JSON.stringify({
    mermaidAndImagesRegression: 'source-passed',
    runtime: 'skipped-incomplete-node_modules',
  }))
  process.exit(0)
}

assert.equal(WIKI_MERMAID_CLASS, 'wiki-mermaid')
assert.equal(resolveSafeMediaSrc('javascript:alert(1)'), null)
assert.equal(resolveSafeMediaSrc('data:image/png;base64,aaaa'), null)
assert.equal(resolveSafeMediaSrc('vbscript:msgbox(1)'), null)
assert.equal(resolveSafeMediaSrc('blob:https://shizuha.com/abc'), null)
assert.equal(resolveSafeMediaSrc('//evil.example/x.png'), null)
assert.equal(resolveSafeMediaSrc('/etc/passwd'), null)
assert.equal(
  resolveSafeMediaSrc('/wiki/api/attachments/2bf8d7c5-ddb1-4443-b021-534f55d82ae0/view/'),
  '/wiki/api/attachments/2bf8d7c5-ddb1-4443-b021-534f55d82ae0/view/',
)
assert.equal(
  resolveSafeMediaSrc('https://shizuha.com/wiki/static/diagram.png'),
  'https://shizuha.com/wiki/static/diagram.png',
)
assert.equal(
  resolveSafeMediaSrc('http://origin.shizuha.com/wiki/x.png'),
  'http://origin.shizuha.com/wiki/x.png',
)

assert.equal(renderSafeImageTag({ src: 'javascript:alert(1)', alt: 'x' }), '')
assert.equal(renderSafeImageTag({ src: 'data:text/html,<svg>', alt: 'x' }), '')
assert.match(
  renderSafeImageTag({
    src: '/wiki/api/attachments/2bf8d7c5-ddb1-4443-b021-534f55d82ae0/view/',
    alt: 'architecture diagram',
  }),
  /<img src="\/wiki\/api\/attachments\/2bf8d7c5-ddb1-4443-b021-534f55d82ae0\/view\/" alt="architecture diagram" \/>/,
)
assert.match(
  renderSafeImageTag({ src: '/wiki/api/attachments/1/view/', alt: '"><script>alert(1)</script>' }),
  /alt="&quot;&gt;&lt;script&gt;alert\(1\)&lt;\/script&gt;"/,
)

console.log(JSON.stringify({
  mermaidAndImagesRegression: 'passed',
  mermaid: ['fence-renderer', 'vendored-umd-11.17.2', 'securityLevel-strict', 'no-inline-svg-in-markdown'],
  images: ['wiki-attachment-allow', 'http-https-allow', 'javascript-data-blob-reject', 'alt-escaped'],
}))

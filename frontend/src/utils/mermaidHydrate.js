import { WIKI_MERMAID_CLASS } from './pageContent'
import { attachMermaidViewer } from './mermaidViewer'
import {
  applyDiagramPrefs,
  diagramRenderKey,
  loadDiagramPrefs,
  mermaidFontForPrefs,
  mermaidThemeForPrefs,
  mermaidThemeVariablesForPrefs,
} from './diagramPrefs'

// Pinned mermaid 11.17.2 UMD bundle copied from the npm dist tarball into
// frontend/public/. Served as a static asset so CI Kaniko does not npm-install
// mermaid's cytoscape/d3/katex tree (that layer snapshot exceeded the 30 min
// wait-pair on wiki-frontend-696c7e0).
const MERMAID_SRC = `${import.meta.env.BASE_URL || '/'}mermaid-11.17.2.min.js`

let mermaidModulePromise = null

function wikiMermaidConfig(prefs) {
  const look = prefs.look === 'neo' || prefs.look === 'handDrawn' ? prefs.look : 'classic'
  const themeVariables = mermaidThemeVariablesForPrefs(prefs)
  const config = {
    startOnLoad: false,
    securityLevel: 'strict',
    theme: mermaidThemeForPrefs(prefs),
    look,
    fontFamily: mermaidFontForPrefs(prefs),
    flowchart: {
      curve: prefs.curve,
      padding: 16,
      nodeSpacing: 40,
      rankSpacing: 52,
      htmlLabels: true,
      wrappingWidth: 160,
      useMaxWidth: true,
    },
    sequence: {
      actorMargin: 48,
      messageMargin: 36,
      mirrorActors: false,
      useMaxWidth: true,
    },
    maxEdges: 500,
  }
  if (look === 'handDrawn') config.handDrawnSeed = 17
  if (themeVariables) config.themeVariables = themeVariables
  return config
}

function roundSvgRects(root, rx) {
  const corner = String(rx)
  root.querySelectorAll('svg rect').forEach((rect) => {
    const cls = `${rect.getAttribute('class') || ''} ${rect.parentElement?.getAttribute('class') || ''}`
    if (/\b(background|actor-line|note)\b/.test(cls)) return
    rect.setAttribute('rx', corner)
    rect.setAttribute('ry', corner)
  })
}

function loadMermaid() {
  if (typeof window !== 'undefined' && window.mermaid) {
    return Promise.resolve(window.mermaid)
  }
  if (mermaidModulePromise) return mermaidModulePromise
  mermaidModulePromise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${MERMAID_SRC}"]`)
    const finish = () => {
      const mermaid = window.mermaid
      if (!mermaid) {
        reject(new Error('mermaid global missing after script load'))
        return
      }
      mermaid.initialize(wikiMermaidConfig(loadDiagramPrefs()))
      resolve(mermaid)
    }
    if (existing) {
      if (window.mermaid) finish()
      else existing.addEventListener('load', finish, { once: true })
      return
    }
    const script = document.createElement('script')
    script.src = MERMAID_SRC
    script.async = true
    script.onload = finish
    script.onerror = () => reject(new Error(`failed to load ${MERMAID_SRC}`))
    document.head.appendChild(script)
  })
  return mermaidModulePromise
}

export async function hydrateWikiMermaid(root, { signal } = {}) {
  if (!root || typeof root.querySelectorAll !== 'function') return 0
  const prefs = applyDiagramPrefs(loadDiagramPrefs())
  const renderKey = diagramRenderKey(prefs)
  const nodes = [...root.querySelectorAll(`.${WIKI_MERMAID_CLASS}`)].filter((el) => (
    el.getAttribute('data-mermaid-done') !== '1'
    || el.getAttribute('data-mermaid-theme') !== renderKey
  ))
  if (!nodes.length) return 0

  const mermaid = await loadMermaid()
  if (signal?.aborted) return 0
  if (typeof document !== 'undefined' && document.fonts?.load && mermaidFontForPrefs(prefs).startsWith('Virgil')) {
    await document.fonts.load('16px Virgil').catch(() => {})
  }
  mermaid.initialize(wikiMermaidConfig(prefs))

  let rendered = 0
  for (const el of nodes) {
    if (signal?.aborted) break
    const source = String(el.getAttribute('data-mermaid-source') || el.textContent || '').trim()
    if (!source) {
      el.setAttribute('data-mermaid-done', '1')
      el.setAttribute('data-mermaid-theme', renderKey)
      continue
    }
    el.setAttribute('data-mermaid-source', source)
    const id = `wiki-mermaid-${Math.random().toString(36).slice(2, 10)}`
    try {
      const { svg } = await mermaid.render(id, source)
      if (signal?.aborted) break
      el.innerHTML = svg
      if (prefs.look !== 'handDrawn') roundSvgRects(el, prefs.cornerRx)
      attachMermaidViewer(el)
      el.removeAttribute('data-mermaid-error')
      el.setAttribute('data-mermaid-done', '1')
      el.setAttribute('data-mermaid-theme', renderKey)
      el.setAttribute('data-diagram-look', prefs.look)
      rendered += 1
    } catch {
      el.setAttribute('data-mermaid-error', '1')
      el.setAttribute('data-mermaid-done', '1')
      el.setAttribute('data-mermaid-theme', renderKey)
    }
  }
  return rendered
}

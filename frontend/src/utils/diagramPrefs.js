import { preferencesApi } from '../services/api'

export const DIAGRAM_PREFS_KEY = 'shizuha_wiki_diagram_prefs'
export const DIAGRAM_PREFS_EVENT = 'wiki-diagram-prefs'

export const DIAGRAM_DEFAULTS = {
  scheme: 'whiteboard',
  look: 'handDrawn',
  cornerRx: 8,
  curve: 'basis',
  scrollZoom: true,
  openFullscreen: true,
}

export const DIAGRAM_PACKS = [
  {
    id: 'whiteboard',
    label: 'Whiteboard',
    hint: 'Excalidraw · default',
    apply: { look: 'handDrawn', scheme: 'whiteboard', curve: 'basis', cornerRx: 8 },
  },
  {
    id: 'classic',
    label: 'Classic',
    hint: 'Solid boxes',
    apply: { look: 'classic', scheme: 'match', curve: 'basis', cornerRx: 8 },
  },
  {
    id: 'neo',
    label: 'Neo',
    hint: '3D bevel',
    apply: { look: 'neo', scheme: 'match', curve: 'basis', cornerRx: 8 },
  },
  {
    id: 'contrast',
    label: 'High contrast',
    hint: 'Sharp ink',
    apply: { look: 'classic', scheme: 'contrast', curve: 'linear', cornerRx: 4 },
  },
]

const LEGACY_DIAGRAM_DEFAULTS = {
  scheme: 'match',
  look: 'classic',
  cornerRx: 8,
  curve: 'basis',
  scrollZoom: true,
  openFullscreen: true,
}

const SCHEMES = new Set(['match', 'dark', 'neutral', 'default', 'forest', 'whiteboard', 'contrast'])
const LOOKS = new Set(['classic', 'neo', 'handDrawn'])
const CURVES = new Set(['basis', 'linear', 'stepAfter'])
const WHITEBOARD_FONT = 'Virgil, "Segoe Print", "Comic Sans MS", cursive'
const UI_FONT = 'ui-sans-serif, system-ui, sans-serif'

function clampRx(n) {
  const v = Number(n)
  if (!Number.isFinite(v)) return DIAGRAM_DEFAULTS.cornerRx
  return Math.min(16, Math.max(0, Math.round(v)))
}

export function normalizeDiagramPrefs(parsed = {}) {
  return {
    scheme: SCHEMES.has(parsed.scheme) ? parsed.scheme : DIAGRAM_DEFAULTS.scheme,
    look: LOOKS.has(parsed.look) ? parsed.look : DIAGRAM_DEFAULTS.look,
    cornerRx: clampRx(parsed.cornerRx),
    curve: CURVES.has(parsed.curve) ? parsed.curve : DIAGRAM_DEFAULTS.curve,
    scrollZoom: parsed.scrollZoom !== false,
    openFullscreen: parsed.openFullscreen !== false,
  }
}

function currentUserId() {
  try {
    const raw = localStorage.getItem('shizuha_user')
    const user = raw ? JSON.parse(raw) : null
    return user?.id ?? null
  } catch {
    return null
  }
}

function cacheKey(userId = currentUserId()) {
  return userId == null ? DIAGRAM_PREFS_KEY : `${DIAGRAM_PREFS_KEY}:${userId}`
}

function readCache(userId = currentUserId()) {
  try {
    const scoped = localStorage.getItem(cacheKey(userId))
    if (scoped) return normalizeDiagramPrefs(JSON.parse(scoped))
    const legacy = localStorage.getItem(DIAGRAM_PREFS_KEY)
    if (legacy) return normalizeDiagramPrefs(JSON.parse(legacy))
  } catch {
    /* ignore */
  }
  return { ...DIAGRAM_DEFAULTS }
}

function writeCache(prefs, userId = currentUserId()) {
  const json = JSON.stringify(prefs)
  localStorage.setItem(cacheKey(userId), json)
  localStorage.setItem(DIAGRAM_PREFS_KEY, json)
}

function prefsEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b)
}

export function loadDiagramPrefs() {
  return readCache()
}

export function diagramRenderKey(prefs = loadDiagramPrefs()) {
  const dark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
  return [prefs.scheme, prefs.look, prefs.cornerRx, prefs.curve, dark ? 'd' : 'l'].join(':')
}

export function mermaidThemeForPrefs(prefs = loadDiagramPrefs()) {
  if (prefs.scheme === 'whiteboard' || prefs.scheme === 'contrast') return 'base'
  if (prefs.look === 'handDrawn' && prefs.scheme === 'match') return 'base'
  if (prefs.scheme === 'match') {
    return typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
      ? 'dark'
      : 'neutral'
  }
  return prefs.scheme
}

function wikiIsDark() {
  return typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
}

export function mermaidFontForPrefs(prefs = loadDiagramPrefs()) {
  if (prefs.look === 'handDrawn' || prefs.scheme === 'whiteboard') return WHITEBOARD_FONT
  return UI_FONT
}

export function mermaidThemeVariablesForPrefs(prefs = loadDiagramPrefs()) {
  const dark = wikiIsDark()
  if (prefs.scheme === 'whiteboard' || (prefs.look === 'handDrawn' && prefs.scheme === 'match')) {
    // Always the light Excalidraw Open Color defaults. Dark wiki applies
    // Excalidraw's invert(93%) hue-rotate(180deg) in CSS so ink, fills, and
    // edge labels stay one palette in-page and in the viewer.
    return {
      darkMode: false,
      background: '#ffffff',
      primaryColor: '#a5d8ff',
      primaryTextColor: '#1e1e1e',
      primaryBorderColor: '#1e1e1e',
      lineColor: '#1e1e1e',
      secondaryColor: '#ffec99',
      tertiaryColor: '#ffffff',
      mainBkg: '#a5d8ff',
      nodeBkg: '#a5d8ff',
      clusterBkg: '#f8f9fa',
      clusterBorder: '#868e96',
      titleColor: '#1e1e1e',
      textColor: '#1e1e1e',
      tertiaryTextColor: '#1e1e1e',
      secondaryTextColor: '#1e1e1e',
      edgeLabelBackground: '#ffffff',
      fontFamily: WHITEBOARD_FONT,
    }
  }
  if (prefs.scheme === 'contrast') {
    if (dark) {
      return {
        darkMode: true,
        background: '#0b0d10',
        primaryColor: '#f1f3f5',
        primaryTextColor: '#111111',
        primaryBorderColor: '#f8f9fa',
        lineColor: '#f8f9fa',
        secondaryColor: '#dee2e6',
        tertiaryColor: '#0b0d10',
        mainBkg: '#f1f3f5',
        clusterBkg: '#212529',
        clusterBorder: '#f8f9fa',
        titleColor: '#f8f9fa',
        textColor: '#f8f9fa',
        edgeLabelBackground: '#0b0d10',
      }
    }
    return {
      darkMode: false,
      background: '#ffffff',
      primaryColor: '#ffffff',
      primaryTextColor: '#000000',
      primaryBorderColor: '#000000',
      lineColor: '#000000',
      secondaryColor: '#f8f9fa',
      tertiaryColor: '#ffffff',
      mainBkg: '#ffffff',
      clusterBkg: '#f8f9fa',
      clusterBorder: '#000000',
      titleColor: '#000000',
      textColor: '#000000',
      edgeLabelBackground: '#ffffff',
    }
  }
  return undefined
}

export function activeDiagramPack(prefs = loadDiagramPrefs()) {
  return DIAGRAM_PACKS.find((pack) => (
    pack.apply.look === prefs.look
    && pack.apply.scheme === prefs.scheme
  ))?.id || null
}

export function applyDiagramPrefs(prefs = loadDiagramPrefs()) {
  if (typeof document === 'undefined') return prefs
  const root = document.documentElement
  root.style.setProperty('--wiki-diagram-rx', `${prefs.cornerRx}px`)
  root.setAttribute('data-diagram-look', prefs.look)
  return prefs
}

function publish(prefs) {
  applyDiagramPrefs(prefs)
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(DIAGRAM_PREFS_EVENT, { detail: prefs }))
  }
  return prefs
}

let pushTimer = null
function scheduleAccountPush(prefs) {
  if (typeof window === 'undefined') return
  clearTimeout(pushTimer)
  pushTimer = setTimeout(() => {
    preferencesApi.patch({ diagrams: prefs }).catch(() => {})
  }, 250)
}

export function saveDiagramPrefs(partial) {
  const next = normalizeDiagramPrefs({ ...loadDiagramPrefs(), ...partial })
  writeCache(next)
  scheduleAccountPush(next)
  return publish(next)
}

export function resetDiagramPrefs() {
  const next = { ...DIAGRAM_DEFAULTS }
  writeCache(next)
  scheduleAccountPush(next)
  return publish(next)
}

export async function hydrateDiagramPrefsFromAccount() {
  const cached = readCache()
  applyDiagramPrefs(cached)
  try {
    const { data } = await preferencesApi.get()
    if (data?.persisted) {
      const next = normalizeDiagramPrefs(data.diagrams || {})
      writeCache(next)
      return publish(next)
    }
    if (prefsEqual(cached, DIAGRAM_DEFAULTS) || prefsEqual(cached, LEGACY_DIAGRAM_DEFAULTS)) {
      writeCache(DIAGRAM_DEFAULTS)
      return publish(DIAGRAM_DEFAULTS)
    }
    if (!prefsEqual(cached, DIAGRAM_DEFAULTS)) {
      await preferencesApi.patch({ diagrams: cached }).catch(() => {})
    }
  } catch {
    /* account API not rolled yet, or offline — cache still applies */
  }
  return cached
}

if (typeof document !== 'undefined') {
  applyDiagramPrefs()
}

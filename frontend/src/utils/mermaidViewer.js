import { loadDiagramPrefs } from './diagramPrefs'
import { rewireCloneIds } from './mermaidCloneIds'

const MIN_ZOOM = 0.15
const MAX_ZOOM = 8
const STAGE_ID = 'wiki-diagram-stage'

function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n))
}

function svgSize(svg) {
  const vb = svg.viewBox?.baseVal
  if (vb && vb.width && vb.height) return { w: vb.width, h: vb.height }
  try {
    const box = svg.getBBox()
    if (box.width && box.height) return { w: box.width, h: box.height }
  } catch {
    /* SVG not in DOM yet */
  }
  const attrW = Number.parseFloat(svg.getAttribute('width') || '')
  const attrH = Number.parseFloat(svg.getAttribute('height') || '')
  const w = (Number.isFinite(attrW) && attrW > 1 ? attrW : 0) || svg.clientWidth || 800
  const h = (Number.isFinite(attrH) && attrH > 1 ? attrH : 0) || svg.clientHeight || 600
  return { w, h }
}

function pinCloneSize(svg) {
  const { w, h } = svgSize(svg)
  rewireCloneIds(svg)
  svg.setAttribute('width', String(w))
  svg.setAttribute('height', String(h))
  svg.style.maxWidth = 'none'
  svg.style.width = `${w}px`
  svg.style.height = `${h}px`
  return { w, h }
}

function closeStage() {
  const stage = document.getElementById(STAGE_ID)
  if (!stage) return
  if (document.fullscreenElement === stage) {
    document.exitFullscreen().catch(() => {})
  }
  stage.remove()
  document.documentElement.classList.remove('wiki-diagram-zen')
}

function openStage(sourceSvg) {
  closeStage()
  const prefs = loadDiagramPrefs()
  const stage = document.createElement('div')
  stage.id = STAGE_ID
  stage.className = 'wiki-diagram-stage'
  stage.setAttribute('role', 'dialog')
  stage.setAttribute('aria-modal', 'true')
  stage.setAttribute('aria-label', 'Diagram viewer')
  const card = sourceSvg.closest('.wiki-mermaid')
  const look = card?.getAttribute('data-diagram-look')
    || document.documentElement.getAttribute('data-diagram-look')
  if (look) stage.setAttribute('data-diagram-look', look)
  if (card && typeof getComputedStyle === 'function') {
    const bg = getComputedStyle(card).backgroundColor
    if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
      stage.style.backgroundColor = bg
    }
  }
  stage.innerHTML = `
    <div class="wiki-diagram-toolbar">
      <button type="button" data-act="fit">Fit</button>
      <button type="button" data-act="out" aria-label="Zoom out">−</button>
      <span class="wiki-diagram-pct" data-pct>100%</span>
      <button type="button" data-act="in" aria-label="Zoom in">+</button>
      <a class="wiki-diagram-settings" href="/wiki/settings#diagrams">Settings</a>
      <button type="button" data-act="close" class="wiki-diagram-close">Close</button>
    </div>
    <div class="wiki-diagram-hint">Scroll to zoom · middle-mouse or Space-drag to pan · Esc to close</div>
    <div class="wiki-diagram-canvas" data-canvas>
      <div class="wiki-diagram-world" data-world></div>
    </div>
  `
  const world = stage.querySelector('[data-world]')
  const canvas = stage.querySelector('[data-canvas]')
  const pctEl = stage.querySelector('[data-pct]')
  const clone = sourceSvg.cloneNode(true)
  pinCloneSize(clone)
  world.appendChild(clone)
  document.body.appendChild(stage)
  document.documentElement.classList.add('wiki-diagram-zen')

  const state = {
    x: 0, y: 0, z: 1, fitZ: 1, dragging: false, px: 0, py: 0, userMoved: false,
    space: false,
  }

  function apply() {
    world.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.z})`
    pctEl.textContent = `${Math.round(state.z * 100)}%`
  }

  function fit() {
    const { w, h } = svgSize(clone)
    const cw = canvas.clientWidth
    const ch = canvas.clientHeight
    if (cw < 32 || ch < 32 || w < 1 || h < 1) return false
    const z = clamp(Math.min(cw / w, ch / h) * 0.92, MIN_ZOOM, MAX_ZOOM)
    state.z = z
    state.fitZ = z
    state.x = (cw - w * z) / 2
    state.y = (ch - h * z) / 2
    apply()
    return true
  }

  function zoomAt(clientX, clientY, nextZ) {
    const z = clamp(nextZ, MIN_ZOOM, MAX_ZOOM)
    const rect = canvas.getBoundingClientRect()
    const cx = clientX - rect.left
    const cy = clientY - rect.top
    const ratio = z / state.z
    state.x = cx - (cx - state.x) * ratio
    state.y = cy - (cy - state.y) * ratio
    state.z = z
    apply()
  }

  function wheelZoomFactor(e) {
    let dy = e.deltaY
    if (e.deltaMode === 1) dy *= 16
    if (e.deltaMode === 2) dy *= 400
    if (dy === 0 && e.deltaX) dy = e.deltaX
    if (Math.abs(dy) >= 32) return dy > 0 ? 1 / 1.12 : 1.12
    return Math.exp(-dy * 0.0025)
  }

  // Excalidraw-style: wheel / pinch zooms toward the cursor. Pan is
  // middle-mouse or Space-drag (left-drag also pans — this is view-only).
  stage.addEventListener('wheel', (e) => {
    e.preventDefault()
    e.stopPropagation()
    state.userMoved = true
    zoomAt(e.clientX, e.clientY, state.z * wheelZoomFactor(e))
  }, { passive: false, capture: true })

  canvas.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 && e.button !== 1) return
    e.preventDefault()
    canvas.setPointerCapture(e.pointerId)
    state.dragging = true
    state.userMoved = true
    state.px = e.clientX
    state.py = e.clientY
    canvas.classList.add('is-panning')
  })
  canvas.addEventListener('pointermove', (e) => {
    if (!state.dragging) return
    state.x += e.clientX - state.px
    state.y += e.clientY - state.py
    state.px = e.clientX
    state.py = e.clientY
    apply()
  })
  const endPan = (e) => {
    if (e.pointerId != null) {
      try { canvas.releasePointerCapture(e.pointerId) } catch { /* already released */ }
    }
    state.dragging = false
    if (!state.space) canvas.classList.remove('is-panning')
  }
  canvas.addEventListener('pointerup', endPan)
  canvas.addEventListener('pointercancel', endPan)
  stage.addEventListener('mousedown', (e) => {
    if (e.button === 1) e.preventDefault()
  })
  stage.addEventListener('auxclick', (e) => e.preventDefault())
  canvas.addEventListener('dblclick', (e) => {
    e.preventDefault()
    if (Math.abs(state.z - state.fitZ) < 0.02) zoomAt(e.clientX, e.clientY, state.z * 1.8)
    else fit()
  })

  stage.querySelector('[data-act="fit"]').addEventListener('click', fit)
  stage.querySelector('[data-act="in"]').addEventListener('click', () => {
    const rect = canvas.getBoundingClientRect()
    zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, state.z * 1.25)
  })
  stage.querySelector('[data-act="out"]').addEventListener('click', () => {
    const rect = canvas.getBoundingClientRect()
    zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, state.z / 1.25)
  })
  stage.querySelector('[data-act="close"]').addEventListener('click', closeStage)
  stage.querySelector('.wiki-diagram-settings')?.addEventListener('click', () => closeStage())

  const onKey = (e) => {
    if (e.code === 'Space') {
      if (!state.space) {
        e.preventDefault()
        state.space = true
        canvas.classList.add('is-panning')
      } else {
        e.preventDefault()
      }
      return
    }
    if (e.key === 'Escape') closeStage()
    const rect = canvas.getBoundingClientRect()
    const cx = rect.left + rect.width / 2
    const cy = rect.top + rect.height / 2
    if (e.key === '+' || e.key === '=') {
      e.preventDefault()
      zoomAt(cx, cy, state.z * 1.25)
    }
    if (e.key === '-' || e.key === '_') {
      e.preventDefault()
      zoomAt(cx, cy, state.z / 1.25)
    }
    if (e.key === '0') {
      e.preventDefault()
      fit()
    }
  }
  const onKeyUp = (e) => {
    if (e.code !== 'Space') return
    state.space = false
    if (!state.dragging) canvas.classList.remove('is-panning')
  }
  document.addEventListener('keydown', onKey)
  document.addEventListener('keyup', onKeyUp)
  const onFs = () => {
    if (document.fullscreenElement === stage) {
      requestAnimationFrame(() => { if (!state.userMoved) fit() })
      return
    }
    if (!document.fullscreenElement && document.getElementById(STAGE_ID) === stage) closeStage()
  }
  document.addEventListener('fullscreenchange', onFs)
  const ro = new ResizeObserver(() => {
    if (!state.userMoved) fit()
  })
  ro.observe(canvas)
  const observer = new MutationObserver(() => {
    if (!document.getElementById(STAGE_ID)) {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('keyup', onKeyUp)
      document.removeEventListener('fullscreenchange', onFs)
      ro.disconnect()
      observer.disconnect()
    }
  })
  observer.observe(document.body, { childList: true })

  requestAnimationFrame(() => {
    fit()
    if (prefs.openFullscreen && stage.requestFullscreen) {
      stage.requestFullscreen().catch(() => {})
    }
  })
}

export function attachMermaidViewer(el) {
  if (!el || el.querySelector(':scope > .wiki-mermaid-chrome')) return
  const svg = el.querySelector('svg')
  if (!svg) return
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.className = 'wiki-mermaid-chrome'
  btn.setAttribute('aria-label', 'Open diagram')
  btn.title = 'Open diagram (pan and zoom)'
  btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg><span>Open</span>`
  btn.addEventListener('click', (e) => {
    e.preventDefault()
    e.stopPropagation()
    const live = el.querySelector('svg')
    if (live) openStage(live)
  })
  el.appendChild(btn)
  svg.addEventListener('dblclick', (e) => {
    e.preventDefault()
    openStage(svg)
  })
}

export function closeMermaidViewer() {
  closeStage()
}

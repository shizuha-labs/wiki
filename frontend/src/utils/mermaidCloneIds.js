function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// Mermaid 11 scopes every fill/stroke/label rule to `#<svgId>`. Cloning then
// dropping the id leaves black unstyled shapes (the fullscreen "empty" map).
export function rewriteMermaidStyleText(css, idMap) {
  if (!css || !idMap?.size) return css
  const entries = [...idMap.entries()].sort((a, b) => b[0].length - a[0].length)
  let out = css
  for (const [oldId, next] of entries) {
    out = out.replace(new RegExp(`#${escapeRegExp(oldId)}\\b`, 'g'), `#${next}`)
  }
  return out
}

export function rewireCloneIds(svg) {
  const suffix = `-zen-${Math.random().toString(36).slice(2, 8)}`
  const nodes = [svg, ...svg.querySelectorAll('[id]')]
  const idMap = new Map()
  for (const el of nodes) {
    const oldId = el.getAttribute('id')
    if (!oldId || idMap.has(oldId)) continue
    idMap.set(oldId, `${oldId}${suffix}`)
  }
  if (!idMap.size) {
    svg.setAttribute('id', `wiki-diagram-clone${suffix}`)
    return
  }
  for (const el of nodes) {
    const oldId = el.getAttribute('id')
    const next = idMap.get(oldId)
    if (next) el.setAttribute('id', next)
  }
  svg.querySelectorAll('style').forEach((style) => {
    style.textContent = rewriteMermaidStyleText(style.textContent, idMap)
  })
  const attrs = [
    'href', 'xlink:href', 'fill', 'stroke', 'filter', 'mask', 'clip-path',
    'marker-start', 'marker-mid', 'marker-end', 'style',
  ]
  svg.querySelectorAll('*').forEach((el) => {
    for (const attr of attrs) {
      const value = el.getAttribute(attr)
      if (value && value.includes('#')) {
        el.setAttribute(attr, rewriteMermaidStyleText(value, idMap))
      }
    }
  })
}

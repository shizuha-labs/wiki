import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({
  breaks: false,
  html: false,
  linkify: false,
  typographer: false,
})

const UUID_LINK = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SAFE_LINK_PROTOCOLS = new Set(['http:', 'https:', 'mailto:', 'tel:'])
const BLOCKED_MEDIA_SCHEMES = /^(javascript|data|vbscript|file|blob):/i
export const WIKI_MERMAID_CLASS = 'wiki-mermaid'
export const WIKI_ATLAS_CLASS = 'wiki-atlas'

export function renderAtlasPlaceholder(source) {
  return `<div class="${WIKI_ATLAS_CLASS} not-prose">${escapeHtml(source)}</div>`
}

function pageOrigin() {
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin
  }
  return 'https://shizuha.com'
}

function resolveSameOriginWikiPath(value) {
  try {
    const url = new URL(value, pageOrigin())
    if (url.origin !== pageOrigin()) return null
    if (!url.pathname.startsWith('/wiki/')) return null
    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    return null
  }
}

function resolveMarkdownLink(href) {
  const value = String(href || '').trim()
  if (!value) return null

  if (UUID_LINK.test(value)) {
    return `/wiki/pages/${encodeURIComponent(value)}/`
  }

  if (value.startsWith('#')) {
    return value
  }

  if (value.startsWith('/wiki/')) {
    return resolveSameOriginWikiPath(value)
  }

  try {
    const url = new URL(value)
    return SAFE_LINK_PROTOCOLS.has(url.protocol) ? value : null
  } catch {
    return null
  }
}

const ATTACHMENT_MEDIA = /\/attachments\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\/(?:view|download)\/?/i

/** Private wiki images 404 in a raw <img> because the browser does not send the JWT. */
export function attachmentIdFromMediaSrc(src) {
  const match = String(src || '').match(ATTACHMENT_MEDIA)
  return match ? match[1] : null
}

export function resolveSafeMediaSrc(src) {
  const value = String(src || '').trim()
  if (!value || value.startsWith('//') || BLOCKED_MEDIA_SCHEMES.test(value)) {
    return null
  }
  if (value.includes('\\') || value.includes('\0')) {
    return null
  }
  if (value.startsWith('/wiki/')) {
    return resolveSameOriginWikiPath(value)
  }
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? value : null
  } catch {
    return null
  }
}

const defaultLinkOpen = markdown.renderer.rules.link_open
markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const token = tokens[index]
  const hrefIndex = token.attrIndex('href')
  const href = hrefIndex >= 0 ? token.attrs[hrefIndex][1] : ''
  const resolvedHref = resolveMarkdownLink(href)

  if (!resolvedHref) {
    token.tag = 'span'
    token.attrs = [['class', 'unsafe-link']]
  } else {
    token.attrs[hrefIndex][1] = resolvedHref
    if (/^https?:\/\//i.test(resolvedHref)) {
      token.attrSet('target', '_blank')
      token.attrSet('rel', 'noopener noreferrer')
    }
  }

  return defaultLinkOpen
    ? defaultLinkOpen(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}

const defaultLinkClose = markdown.renderer.rules.link_close
markdown.renderer.rules.link_close = (tokens, index, options, env, self) => {
  const open = tokens.slice(0, index).reverse().find((token) => (
    token.type === 'link_open' || token.type === 'link_close'
  ))

  if (open?.type === 'link_open' && open.tag === 'span') {
    tokens[index].tag = 'span'
  }

  return defaultLinkClose
    ? defaultLinkClose(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll(String.fromCharCode(34), '&quot;')
    .replaceAll("'", '&#39;')
}

export function renderSafeImageTag(attrs = {}) {
  const src = resolveSafeMediaSrc(attrs.src)
  if (!src) return ''
  const alt = escapeHtml(attrs.alt || '')
  const title = attrs.title ? ` title="${escapeHtml(attrs.title)}"` : ''
  const width = Number.isFinite(Number(attrs.width)) && Number(attrs.width) > 0
    ? ` width="${String(Math.trunc(Number(attrs.width)))}"`
    : ''
  const height = Number.isFinite(Number(attrs.height)) && Number(attrs.height) > 0
    ? ` height="${String(Math.trunc(Number(attrs.height)))}"`
    : ''
  return `<img src="${escapeHtml(src)}" alt="${alt}"${title}${width}${height} />`
}

const defaultImage = markdown.renderer.rules.image
markdown.renderer.rules.image = (tokens, index, options, env, self) => {
  const token = tokens[index]
  const srcIndex = token.attrIndex('src')
  const src = srcIndex >= 0 ? token.attrs[srcIndex][1] : ''
  const resolved = resolveSafeMediaSrc(src)
  if (!resolved) {
    return ''
  }
  token.attrs[srcIndex][1] = resolved
  return defaultImage
    ? defaultImage(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}

const defaultFence = markdown.renderer.rules.fence
markdown.renderer.rules.fence = (tokens, index, options, env, self) => {
  const token = tokens[index]
  const info = String(token.info || '').trim().split(/\s+/)[0].toLowerCase()
  if (info === 'mermaid') {
    return `<div class="${WIKI_MERMAID_CLASS} not-prose">${escapeHtml(token.content.trim())}</div>\n`
  }
  if (info === 'atlas') return `${renderAtlasPlaceholder(token.content.trim())}\n`
  return defaultFence
    ? defaultFence(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}

function sanitize(html) {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      'a', 'blockquote', 'br', 'code', 'del', 'div', 'em', 'h1', 'h2', 'h3', 'h4',
      'h5', 'h6', 'hr', 'img', 'li', 'mark', 'ol', 'p', 'pre', 'span', 'strong',
      'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul',
    ],
    ALLOWED_ATTR: ['class', 'href', 'id', 'rel', 'target', 'src', 'alt', 'title', 'width', 'height'],
    ALLOW_DATA_ATTR: false,
    FORBID_TAGS: ['svg', 'script', 'iframe', 'object', 'embed', 'form', 'math'],
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel):|\/wiki\/|#)/i,
  })
}

function isMarkdownSource(contentJson, contentText) {
  const body = String(contentText || '')
  if (!body.trim()) return false

  if (!contentJson || contentJson.type !== 'doc' || !Array.isArray(contentJson.content)) {
    return true
  }

  const jsonText = extractText(contentJson)
  if (!jsonText.trim()) return true

  // MCP/section-update fallbacks persist Markdown as literal paragraph text in
  // content_json. Prefer content_text only when Markdown syntax is still visible
  // in the JSON projection; genuine TipTap rich text may have the same plain text
  // projection and must keep its marks, tables, and editor-only nodes.
  // WIKI-93: compare with block-marker tokens stripped from BOTH sides — the
  // strict equality misclassified mixed-persistence pages (real heading nodes +
  // literal-Markdown bodies) because the projection cannot represent heading/list
  // markers as text, sending them to the rich-text path where the literal
  // Markdown rendered raw.
  // PLAT-10013: literal fenced-code text inside paragraph nodes is DECISIVE
  // evidence of Markdown persistence — genuine TipTap rich text stores fences
  // as codeBlock nodes, never as literal ``` text. Mixed-persistence pages
  // (real heading nodes + literal-Markdown bodies) diverge from content_text
  // on inline marks (bold/links become node attrs, dropping ** and []() from
  // the projection), so the equality below fails and their ```mermaid fences
  // render as raw text instead of hydrating. Route them to the Markdown path
  // before the strict check.
  if (fenceMarkerCount(jsonText) > 0) {
    return true
  }

  return containsMarkdownSyntax(jsonText)
    && stripBlockMarkerTokens(jsonText) === stripBlockMarkerTokens(body)
}

function fenceMarkerCount(value) {
  return (String(value || '').match(/```/g) || []).length
}

function stripBlockMarkerTokens(value) {
  // Block-structure markers (heading levels, list bullets/numbers, blockquotes)
  // live in TipTap node attributes, not text nodes — the JSON projection drops
  // them, while the server-side Markdown serialization keeps them. Mixed
  // persistence on one page (real heading nodes + Markdown persisted literally
  // in paragraph/list text nodes — the MCP/section-update fallback) produces
  // BOTH divergence classes at once. Strip the marker tokens from BOTH
  // projections before comparing; inline syntax (**, links, pipes, inline
  // code) is untouched, so genuine rich text still fails the equality and
  // keeps its marks, tables, and editor-only nodes.
  return normalizeWhitespace(value)
    .replace(/(^|\s)#{1,6}\s+/g, '$1')
    .replace(/(^|\s)[-+]\s+/g, '$1')
    .replace(/(^|\s)\*\s+/g, '$1')
    .replace(/(^|\s)\d{1,3}\.\s+/g, '$1')
    .replace(/(^|\s)>\s?/g, '$1')
}

function nodeText(node) {
  if (!node) return ''
  if (node.type === 'text') return node.text || ''
  if (!Array.isArray(node.content)) return ''
  return node.content.map(nodeText).join('')
}

function extractText(node) {
  if (!node) return ''
  if (node.type === 'text') return node.text || ''
  if (!Array.isArray(node.content)) return ''
  return node.content.map(extractText).join(' ')
}

function containsMarkdownSyntax(value) {
  return /(^|\n)\s{0,3}(?:#{1,6}\s|[-*+]\s|\d+\.\s|>\s|```|\|.+\|)|\*\*[^*]+\*\*|(?<!\*)\*[^*\n]+\*(?!\*)|`[^`\n]+`|\[[^\]]+\]\([^)]+\)/m.test(value)
}

function normalizeWhitespace(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

export function markdownHeadings(contentText) {
  const headings = []
  const tokens = markdown.parse(String(contentText || ''), {})
  tokens.forEach((token, index) => {
    if (token.type === 'heading_open') {
      headings.push({
        level: Number(token.tag.slice(1)) || 1,
        text: tokens[index + 1]?.content || '',
        id: `heading-${headings.length}`,
      })
    }
  })
  return headings
}

export function renderTableOfContents(headings) {
  if (!headings?.length) return ''
  const items = headings.map((heading) => (
    `<li class="toc-level-${heading.level}" style="padding-left: ${(heading.level - 1) * 16}px;">`
      + `<a href="#${heading.id}">${escapeHtml(heading.text || 'Untitled')}</a></li>`
  )).join('')
  return `<div class="toc-rendered"><div class="toc-header"><span class="toc-title">On this page</span></div><ul class="toc-list">${items}</ul></div>`
}

export function tipTapHeadings(contentJson) {
  const headings = []
  const visit = (node) => {
    if (!node) return
    if (node.type === 'heading') {
      headings.push({
        level: node.attrs?.level || 1,
        text: nodeText(node),
        id: `heading-${headings.length}`,
      })
    }
    node.content?.forEach(visit)
  }
  visit(contentJson)
  return headings
}

export function renderMarkdownContent(contentText) {
  const tokens = markdown.parse(String(contentText || ''), {})
  let headingIndex = 0
  tokens.forEach((token) => {
    if (token.type === 'heading_open') {
      token.attrSet('id', `heading-${headingIndex++}`)
    }
  })
  return sanitize(markdown.renderer.render(tokens, markdown.options, {}))
}

export function shouldRenderMarkdown(contentJson, contentText) {
  return isMarkdownSource(contentJson, contentText)
}

export function sanitizePageContent(html) {
  return sanitize(html)
}

// ---------------------------------------------------------------------------
// WIKI-120: TipTap doc → Markdown serialization for editor save paths.
//
// The editor save paths used to persist `content_text: editor.getText()`,
// which flattens any structured page: heading levels live in node attributes
// (so `# Context & problem` became `Context & problem`) and fence delimiters
// live in the node type (so ``` fences vanished). This serializer emits
// Markdown that re-parses to an equivalent document; code-block content is
// byte-verbatim between the fence lines, including `#` comment lines.
// ---------------------------------------------------------------------------

function serializeInline(node, context = {}) {
  if (!node) return ''
  if (node.type === 'text') {
    let text = String(node.text ?? '')
    const marks = node.marks || []
    const has = (name) => marks.some((m) => m.type === name)
    // Underline/highlight have no Markdown equivalent the renderer's
    // sanitizer accepts; serialize their text bare rather than emitting
    // tags that markdown-it (html:false) would escape.
    if (has('code')) {
      return '`' + text + '`'
    }
    if (has('link')) {
      const link = marks.find((m) => m.type === 'link')
      const href = link?.attrs?.href || ''
      return `[${text}](${href})`
    }
    let out = text
    if (has('bold')) out = `**${out}**`
    if (has('italic')) out = `*${out}*`
    if (has('strike')) out = `~~${out}~~`
    return out
  }
  if (node.type === 'hardBreak') return '\n'
  if (Array.isArray(node.content)) {
    return node.content.map((child) => serializeInline(child, context)).join('')
  }
  return ''
}

function serializeBlocks(nodes, depth = 0) {
  if (!Array.isArray(nodes)) return []
  return nodes.map((node) => serializeBlock(node, depth)).filter((v) => v !== null)
}

function serializeBlock(node, depth = 0) {
  if (!node) return null
  const indent = '  '.repeat(depth)
  switch (node.type) {
    case 'heading': {
      const level = Math.min(6, Math.max(1, node.attrs?.level || 1))
      return `${'#'.repeat(level)} ${serializeInline(node).trim()}`
    }
    case 'paragraph':
      return indent + serializeInline(node)
    case 'codeBlock': {
      const lang = node.attrs?.language || ''
      const code = serializeCodeText(node)
      return '```' + lang + '\n' + code + (code.endsWith('\n') ? '' : '\n') + '```'
    }
    case 'bulletList': {
      const items = serializeBlocks(node.content, depth + 1)
      return items.map((item) => `${indent}- ${item}`).join('\n\n')
    }
    case 'orderedList': {
      const items = serializeBlocks(node.content, depth + 1)
      return items.map((item, i) => `${indent}${i + 1}. ${item}`).join('\n\n')
    }
    case 'listItem':
    case 'taskItem': {
      // Items render their children; a checkbox state is emitted by the
      // parent taskList's item mapping below.
      return serializeBlocks(node.content, depth).join('\n\n')
    }
    case 'taskList': {
      const items = (node.content || []).map((item) => {
        const checked = item.attrs?.checked ? '[x] ' : '[ ] '
        const body = serializeBlocks(item.content, depth + 1).join('\n\n')
        return `${indent}- ${checked}${body}`
      })
      return items.join('\n\n')
    }
    case 'blockquote': {
      const body = serializeBlocks(node.content, depth).join('\n\n')
      return body.split('\n').map((line) => `> ${line}`).join('\n')
    }
    case 'callout': {
      const body = serializeBlocks(node.content, depth).join('\n\n')
      return body.split('\n').map((line) => `> ${line}`).join('\n')
    }
    case 'horizontalRule':
      return '---'
    case 'image':
      return `![${node.attrs?.alt || ''}](${node.attrs?.src || ''})`
    case 'table':
      return serializeTable(node)
    default: {
      if (Array.isArray(node.content)) {
        const body = serializeBlocks(node.content, depth).join('\n\n')
        return body || null
      }
      const inline = serializeInline(node)
      return inline || null
    }
  }
}

function serializeCodeText(node) {
  const parts = []
  const visit = (n) => {
    if (!n) return
    if (n.type === 'text') {
      parts.push(String(n.text ?? ''))
      return
    }
    if (Array.isArray(n.content)) n.content.forEach(visit)
  }
  visit(node)
  return parts.join('')
}

function serializeTable(node) {
  const rows = (node.content || []).filter((r) => r.type === 'tableRow')
  if (!rows.length) return null
  const cells = (row) =>
    (row.content || []).map((cell) =>
      serializeBlocks(cell.content, 0).join('<br>').replace(/\n/g, '<br>') || ' '
    )
  const header = cells(rows[0])
  const lines = [
    `| ${header.join(' | ')} |`,
    `| ${header.map(() => '---').join(' | ')} |`,
  ]
  rows.slice(1).forEach((row) => {
    lines.push(`| ${cells(row).join(' | ')} |`)
  })
  return lines.join('\n')
}

export function docToMarkdown(doc) {
  if (!doc || doc.type !== 'doc' || !Array.isArray(doc.content)) {
    return ''
  }
  const blocks = serializeBlocks(doc.content, 0)
  return blocks.filter((b) => b !== null && b !== '').join('\n\n') + '\n'
}

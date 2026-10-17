export const WIKI_BASE = '/wiki'

export function canonicalPagePath(page) {
  if (!page?.space_key || !page?.slug) {
    throw new Error('Canonical page metadata requires space_key and slug')
  }

  return `/spaces/${encodeURIComponent(page.space_key)}/pages/${encodeURIComponent(page.slug)}`
}

export function canonicalPageDocumentPath(page) {
  return `${WIKI_BASE}${canonicalPagePath(page)}`
}

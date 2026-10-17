const PATHS = new Set(['/atlas', '/atlas/editor'])

export function atlasLauncherHref(path, organization, guide = false) {
  if (!PATHS.has(path)) throw new Error('Unsupported Atlas destination')
  const query = new URLSearchParams()
  if (typeof organization === 'string' && /^[1-9][0-9]{0,15}$/.test(organization) && Number.isSafeInteger(Number(organization))) query.set('organization', organization)
  if (guide === true) query.set('guide', '1')
  return path + (query.size ? `?${query}` : '')
}

if (typeof document !== 'undefined') {
  let organization = null
  try { organization = localStorage.getItem('shizuha_organization_id') } catch { organization = null }
  for (const link of document.querySelectorAll('a[data-atlas-path]')) {
    link.setAttribute('href', atlasLauncherHref(link.dataset.atlasPath, organization, link.dataset.atlasGuide === 'true'))
  }
}

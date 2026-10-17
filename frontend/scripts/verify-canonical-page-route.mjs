import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import {
  WIKI_BASE,
  canonicalPageDocumentPath,
  canonicalPagePath,
} from '../src/utils/canonicalPage.js'

assert.equal(WIKI_BASE, '/wiki')

assert.equal(
  canonicalPagePath({
    space_key: 'OPS',
    slug: 'runbook-shizuha-edge-wildcard-tls-for-product-hosts',
  }),
  '/spaces/OPS/pages/runbook-shizuha-edge-wildcard-tls-for-product-hosts',
)

assert.equal(
  canonicalPagePath({ space_key: 'A B', slug: 'page/with slash' }),
  '/spaces/A%20B/pages/page%2Fwith%20slash',
)

assert.equal(
  canonicalPageDocumentPath({ space_key: 'A B', slug: 'page/with slash' }),
  '/wiki/spaces/A%20B/pages/page%2Fwith%20slash',
)

assert.throws(
  () => canonicalPagePath({ space_key: 'OPS' }),
  /requires space_key and slug/,
)
assert.throws(
  () => canonicalPagePath({ slug: 'page' }),
  /requires space_key and slug/,
)
assert.throws(
  () => canonicalPagePath(null),
  /requires space_key and slug/,
)

const appSource = await readFile(
  fileURLToPath(new URL('../src/App.jsx', import.meta.url)),
  'utf8',
)
assert.match(
  appSource,
  /<Route\s+path=[\"']:pageId[\"']\s+element=\{<CanonicalPageRedirect\s*\/>\}\s*\/>/,
  'App route table must register the canonical :pageId redirect',
)

const redirectSource = await readFile(
  fileURLToPath(new URL('../src/pages/CanonicalPageRedirect.jsx', import.meta.url)),
  'utf8',
)
assert.match(
  redirectSource,
  /if \(isError \|\| !page\?\.space_key \|\| !page\?\.slug\)/,
  'redirect must fail closed on incomplete canonical metadata',
)
assert.match(
  redirectSource,
  /const canonicalPath = canonicalPagePath\(page\)/,
  'redirect must construct the canonical path only after its metadata guard',
)
assert.ok(
  redirectSource.indexOf('if (isError || !page?.space_key || !page?.slug)') <
    redirectSource.indexOf('const canonicalPath = canonicalPagePath(page)'),
  'metadata guard must execute before canonicalPagePath',
)

// PLAT-5192: a bare canonical UUID carries no tenant. The org-scoped client
// pins the lookup to the previously selected organization, so a page the user
// can legitimately read in another membership 404s. The backend aggregates
// only when X-Organization-ID is ABSENT — a sentinel value does not work.
assert.match(
  redirectSource,
  /pagesApi\.getAcrossOrganizations\(pageId\)/,
  'canonical redirect must resolve across memberships, not through the org-scoped client',
)
assert.doesNotMatch(
  redirectSource,
  /pagesApi\.get\(pageId\)/,
  'canonical redirect must not use the org-scoped pagesApi.get — that is the PLAT-5192 defect',
)

const apiSource = await readFile(
  fileURLToPath(new URL('../src/services/api.js', import.meta.url)),
  'utf8',
)
assert.match(
  apiSource,
  /getAcrossOrganizations:\s*\(id\)\s*=>\s*\n?\s*api\.get\(`\/pages\/\$\{id\}\/`,\s*\{\s*skipOrganizationHeader:\s*true\s*\}\)/,
  'pagesApi must expose an organization-agnostic page read',
)
assert.match(
  apiSource,
  /if \(orgId && !config\.skipOrganizationHeader\)/,
  'the request interceptor must honour the per-request organization opt-out',
)

// Resolving the UUID is only half of it: the canonical route re-fetches through
// the org-scoped client, so a cross-tenant deep link that does not adopt the
// page's organization resolves here and then 404s one navigation later.
assert.match(
  redirectSource,
  /localStorage\.setItem\(ORG_ID_KEY, resolvedOrgId\)/,
  'redirect must adopt the resolved page organization before handing off',
)
assert.ok(
  redirectSource.indexOf('localStorage.setItem(ORG_ID_KEY, resolvedOrgId)') <
    redirectSource.indexOf('window.location.assign('),
  'organization must be persisted before the canonical navigation, not after',
)
assert.match(
  redirectSource,
  /window\.location\.assign\(\s*`\$\{canonicalPageDocumentPath\(page\)\}/,
  'full-document organization handoff must retain the /wiki application base',
)

const mainSource = await readFile(
  fileURLToPath(new URL('../src/main.jsx', import.meta.url)),
  'utf8',
)
// Wiki's router base is WIKI_BASE. Atlas is a separate application at /atlas/.
assert.match(
  mainSource,
  /<BrowserRouter\s+basename=\{WIKI_BASE\}/,
  'router basename must stay WIKI_BASE',
)
assert.doesNotMatch(mainSource, /isAtlasApp/, 'Wiki must not host the Atlas application')
assert.match(redirectSource, />\s*Page unavailable\s*</)

console.log('canonical page route contract verified')

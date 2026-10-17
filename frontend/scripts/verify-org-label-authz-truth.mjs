// PLAT-8302 truth-audit regression: the wiki SPA must NOT render a false
// "No Organization" from a 401/403 authz failure on /admin/api/organizations/.
// The fetch must carry the failure status to the UI, and the sidebar org
// label must render an access-denied state for 401/403 — "No Organization"
// only after a successful load with an actually-empty membership set.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const authSource = await readFile(
  fileURLToPath(new URL('../src/contexts/AuthContext.jsx', import.meta.url)),
  'utf8',
)

// 1. The org fetch must return a structured error, not silently collapse
//    every failure into [].
assert.match(
  authSource,
  /return \{ orgs: response\.data\.results \|\| response\.data \|\| \[\], error: null \}/,
  'successful org fetch must return { orgs, error: null }',
)
assert.match(
  authSource,
  /return \{ orgs: \[\], error: \{ status, code \} \}/,
  'failed org fetch must return { orgs: [], error: { status, code } } — never a bare []',
)
assert.doesNotMatch(
  authSource,
  /catch \(error\) \{\s*console\.error\('Failed to fetch organizations:', error\)\s*return \[\]\s*\}/,
  'the old error-swallowing `return []` path must not come back',
)

// 2. The provider must expose the error to consumers.
assert.match(
  authSource,
  /const \[orgsError, setOrgsError\] = useState\(null\)/,
  'AuthProvider must hold orgsError state',
)
assert.match(
  authSource,
  /setOrgsError\(orgsFetchError\)/,
  'AuthProvider must persist the fetch error into orgsError',
)
assert.match(
  authSource,
  /\n\s{4}orgsError,\n/,
  'context value must expose orgsError',
)

// 3. The sidebar label must distinguish access-denied from empty.
const layoutSource = await readFile(
  fileURLToPath(new URL('../src/components/Layout.jsx', import.meta.url)),
  'utf8',
)
assert.match(
  layoutSource,
  /orgsError\.status === 401 \|\| orgsError\.status === 403/,
  'Layout must branch on 401/403 orgsError',
)
assert.match(
  layoutSource,
  /isAuthzDenied \? 'Organization access denied' : 'No Organization'/,
  "the 401/403 path must render 'Organization access denied', not 'No Organization'",
)
assert.match(
  layoutSource,
  /organization\?\.name\s*\|\|/,
  "a successfully-loaded organization name still wins over any fallback",
)

console.log('verify-org-label-authz-truth: all assertions passed')

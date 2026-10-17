/**
 * PLAT-4443 — follow-redirects GHSA-r4q5-vmmm-2653
 *
 * Transitive-override consumer-boundary regression (verify-before-push):
 * real consumer is axios (frontend/src/services/api.js, AuthContext.jsx),
 * which imports follow-redirects in its Node http adapter. Coverage crosses
 * axios's public HTTP API with a cross-origin redirect and the
 * sensitiveHeaders option introduced/required on the patched 1.16.0 line —
 * not a direct leaf-only import.
 */
import assert from 'node:assert/strict'
import http from 'node:http'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)

function parseSemver(version) {
  const [major, minor, patch] = String(version).split('.').map(Number)
  return [major, minor, patch]
}

function gte(version, minimum) {
  const [aMaj, aMin, aPat] = parseSemver(version)
  const [bMaj, bMin, bPat] = parseSemver(minimum)
  if (aMaj !== bMaj) return aMaj > bMaj
  if (aMin !== bMin) return aMin > bMin
  return aPat >= bPat
}

function listen(server, host, port = 0) {
  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(port, host, () => {
      const addr = server.address()
      resolve(addr.port)
    })
  })
}

function close(server) {
  return new Promise((resolve) => server.close(() => resolve()))
}

// --- version / tree evidence -------------------------------------------------
assert.doesNotThrow(() => require.resolve('axios/package.json'))
const axiosPkg = require('axios/package.json')
assert.equal(axiosPkg.name, 'axios')

const frPkg = require('follow-redirects/package.json')
const pinned = require('../package.json').overrides?.['follow-redirects']
assert.equal(pinned, '1.16.0')
assert.ok(
  gte(frPkg.version, '1.16.0'),
  `expected follow-redirects >=1.16.0, got ${frPkg.version}`,
)
assert.equal(frPkg.version, pinned)

// --- axios consumer boundary: cross-origin redirect header strip ------------
// 127.0.0.1 vs localhost are different hosts → cross-origin for follow-redirects.
const captured = { headers: null, hit: false }

const target = http.createServer((req, res) => {
  captured.hit = true
  captured.headers = { ...req.headers }
  res.writeHead(200, { 'content-type': 'application/json' })
  res.end(JSON.stringify({ ok: true }))
})

const origin = http.createServer((req, res) => {
  const port = target.address().port
  // Redirect to a different host (localhost ≠ 127.0.0.1).
  res.writeHead(302, { Location: `http://localhost:${port}/landed` })
  res.end()
})

const originPort = await listen(origin, '127.0.0.1')
const targetPort = await listen(target, 'localhost')
assert.ok(originPort > 0 && targetPort > 0)

try {
  // Dynamic import keeps this ESM script aligned with the app's axios usage.
  const axios = (await import('axios')).default

  const response = await axios.get(`http://127.0.0.1:${originPort}/start`, {
    headers: {
      'X-API-Key': 'sk-live-regression-secret',
      Authorization: 'Bearer should-also-strip',
    },
    // Patched axios + follow-redirects 1.16.0 surface: extend sensitive set.
    sensitiveHeaders: ['X-API-Key'],
    maxRedirects: 5,
    validateStatus: () => true,
    // Force Node http adapter (follow-redirects path), not browser XHR.
    adapter: 'http',
    timeout: 5000,
  })

  assert.equal(response.status, 200)
  assert.equal(captured.hit, true, 'redirect target must receive the follow-up request')
  assert.equal(
    captured.headers['x-api-key'],
    undefined,
    'X-API-Key must not leak across cross-origin redirect (GHSA-r4q5)',
  )
  assert.equal(
    captured.headers.authorization,
    undefined,
    'Authorization must not leak across cross-origin redirect',
  )
  assert.deepEqual(response.data, { ok: true })
} finally {
  await close(origin)
  await close(target)
}

console.log(JSON.stringify({
  followRedirectsSecurityRegression: 'passed',
  followRedirectsVersion: frPkg.version,
  axiosVersion: axiosPkg.version,
  consumer: 'axios http adapter',
  advisory: 'GHSA-r4q5-vmmm-2653',
  checked: ['version>=1.16.0', 'cross-origin X-API-Key strip via axios'],
}))

// Silence unused import lint-style noise if bundlers scan this file.
void pathToFileURL

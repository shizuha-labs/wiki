import assert from 'node:assert/strict'
import { performance } from 'node:perf_hooks'

import { parse } from 'flatted'

// flatted is the serialization boundary used by eslint -> flat-cache in this
// frontend. Exercise the installed package directly so lockfile regressions
// cannot silently restore either advisory at that boundary.
const depth = 20_000
const entries = Array.from({ length: depth + 1 }, (_, index) => (
  index === depth ? { next: null } : { next: String(index + 1) }
))

const startedAt = performance.now()
let cursor = parse(JSON.stringify(entries))
const elapsedMs = performance.now() - startedAt

for (let index = 0; index < depth; index += 1) {
  assert.equal(typeof cursor, 'object', `reference ${index} must resolve to an object`)
  cursor = cursor.next
}
assert.equal(cursor.next, null)
assert.ok(elapsedMs < 5_000, `20k-reference payload took ${elapsedMs.toFixed(1)}ms`)

const pollutionMarker = '__flattedSecurityRegression__'
for (const reference of ['__proto__', 'constructor']) {
  delete Array.prototype[pollutionMarker]
  delete Object.prototype[pollutionMarker]
  delete Array[pollutionMarker]

  const parsed = parse(JSON.stringify([{ value: reference }]))
  assert.equal(parsed.value, undefined, `${reference} must not resolve through Array inheritance`)

  if (parsed.value && (typeof parsed.value === 'object' || typeof parsed.value === 'function')) {
    parsed.value[pollutionMarker] = true
  }

  assert.equal(Array.prototype[pollutionMarker], undefined)
  assert.equal(Object.prototype[pollutionMarker], undefined)
  assert.equal(Array[pollutionMarker], undefined)
}

console.log(JSON.stringify({
  flattedSecurityRegression: 'passed',
  referenceDepth: depth,
  elapsedMs: Number(elapsedMs.toFixed(1)),
  rejectedInheritedReferences: ['__proto__', 'constructor'],
}))

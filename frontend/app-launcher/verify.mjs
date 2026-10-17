import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { atlasLauncherHref } from './navigation.mjs'

assert.equal(atlasLauncherHref('/atlas', '17'), '/atlas?organization=17')
assert.equal(atlasLauncherHref('/atlas/editor', '17'), '/atlas/editor?organization=17')
assert.equal(atlasLauncherHref('/atlas', '17', true), '/atlas?organization=17&guide=1')
assert.equal(atlasLauncherHref('/atlas', null, true), '/atlas?guide=1')
for (const value of ['', '0', '01', '-1', '1e3', '1.5', '9007199254740992', '17&redirect=https://evil.invalid', 'https://evil.invalid', 17, null, undefined]) assert.equal(atlasLauncherHref('/atlas', value), '/atlas')
for (const path of ['//evil.invalid', 'https://evil.invalid', '/atlas?redirect=evil', '/atlas/editor/../other', '/atlas#fragment', '/wiki/atlas']) assert.throws(() => atlasLauncherHref(path, '17'))
const html = await readFile(new URL('./index.html', import.meta.url), 'utf8')
assert.doesNotMatch(html, /<iframe|https?:\/\/|<script[^>]*>[^<]+<\/script>/i)
assert.match(html, /data-atlas-guide="true"/)
assert.match(html, /Concept view/)
assert.match(html, /not a live system map/i)
console.log('Atlas launcher: fixed destinations, strict organization scope, inert preview and offline assets verified')

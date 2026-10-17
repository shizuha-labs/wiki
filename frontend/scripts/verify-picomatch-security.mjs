// PLAT-4449: consumer-boundary regression for the transitive picomatch override
// (overrides pin picomatch@<3 -> 2.3.2 and picomatch@>=4 <5 -> 4.0.4). Exercises
// the REAL consumers, not picomatch directly, so a lockfile regression that
// restored either advisory at the boundary this frontend actually uses would fail:
//   - picomatch 2.x line: micromatch (also anymatch/readdirp) -> require 2.3.2
//   - picomatch 4.x line: tinyglobby -> require 4.0.4
// Advisories:
//   GHSA-c2c7-rcm5-vvqj — ReDoS via extglob quantifiers (e.g. +(+(a)), *(+(a)));
//     ~29s to reject a 33-char non-matching input on unpatched. Fixed 2.3.2 / 4.0.4.
//   GHSA-3v7f-55p6-f55p — method injection in POSIX character classes -> incorrect
//     glob matching. Fixed 2.3.2.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const micromatch = require('micromatch')
const frontendRoot = fileURLToPath(new URL('..', import.meta.url))

// --- The consumers resolve the exact patched picomatch lines ---
const mmPicomatch = require.resolve('picomatch/package.json', {
  paths: [require.resolve('micromatch')],
})
const pm2 = require(mmPicomatch)
assert.equal(pm2.version, '2.3.2', `micromatch's picomatch (2.x) must be 2.3.2, got ${pm2.version}`)
const tgPicomatch = require.resolve('picomatch/package.json', {
  paths: [require.resolve('tinyglobby')],
})
const pm4 = require(tgPicomatch)
assert.equal(pm4.version, '4.0.4', `tinyglobby's picomatch (4.x) must be 4.0.4, got ${pm4.version}`)

// --- Happy path through the consumers ---
assert.equal(micromatch.isMatch('src/index.js', '**/*.js'), true)
assert.equal(micromatch.isMatch('src/index.ts', '**/*.js'), false)
assert.deepEqual(micromatch(['a.js', 'b.ts', 'c.js'], '*.js'), ['a.js', 'c.js'])

// --- GHSA-3v7f-55p6-f55p: POSIX character class matches correctly (patched) ---
assert.equal(micromatch.isMatch('a', '[[:alpha:]]'), true)
assert.equal(micromatch.isMatch('1', '[[:alpha:]]'), false)
assert.equal(micromatch.isMatch('5', '[[:digit:]]'), true)

// --- GHSA-c2c7-rcm5-vvqj ReDoS, 2.x line via micromatch, out of process + hard
// timeout so a regressed (pre-2.3.2) dep is killed instead of hanging the runner ---
const redos2 = execFileSync(
  process.execPath,
  ['-e', "const mm=require('micromatch');process.stdout.write(String(mm.isMatch('a'.repeat(40)+'b','+(+(a))')))"],
  { cwd: frontendRoot, encoding: 'utf8', timeout: 3_000 },
)
assert.equal(redos2, 'false')

// --- GHSA-c2c7-rcm5-vvqj ReDoS, 4.x line via tinyglobby, out of process + timeout.
// A non-matching filename forces tinyglobby's picomatch-4 matcher to reject via the
// vulnerable extglob pattern; patched returns [] fast, a regressed dep hangs -> killed ---
const redos4 = execFileSync(
  process.execPath,
  ['-e', [
    "const os=require('os'),fs=require('fs'),path=require('path');",
    "const d=fs.mkdtempSync(path.join(os.tmpdir(),'pm4-'));",
    "fs.writeFileSync(path.join(d,'zzzzzzzzzzzzzzzzzzzzzzzzzzzzzz.txt'),'x');",
    "const {globSync}=require('tinyglobby');",
    "process.stdout.write(JSON.stringify(globSync(['+(+(a))'],{cwd:d})));",
  ].join('')],
  { cwd: frontendRoot, encoding: 'utf8', timeout: 4_000 },
)
assert.deepEqual(JSON.parse(redos4), [])

console.log(JSON.stringify({
  picomatchConsumerBoundaryRegression: 'passed',
  picomatch2xViaMicromatch: pm2.version,
  picomatch4xViaTinyglobby: pm4.version,
  redosExtglobRejectedFast: true,
  posixClassMatching: 'correct',
}))

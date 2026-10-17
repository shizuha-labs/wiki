import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const minimatch = require('minimatch')

assert.deepEqual(
  minimatch.braceExpand('file{1..3}.txt'),
  ['file1.txt', 'file2.txt', 'file3.txt'],
)

// Run the advisory payload out of process so a regressed dependency is killed
// instead of hanging or exhausting the test runner.
const frontendRoot = fileURLToPath(new URL('..', import.meta.url))
const zeroStepOutput = execFileSync(
  process.execPath,
  [
    '-e',
    "const minimatch=require('minimatch');process.stdout.write(JSON.stringify(minimatch.braceExpand('{1..2..0}')))",
  ],
  {
    cwd: frontendRoot,
    encoding: 'utf8',
    timeout: 2_000,
  },
)

assert.deepEqual(JSON.parse(zeroStepOutput), ['1', '2'])

console.log(JSON.stringify({
  braceExpansionSecurityRegression: 'passed',
  normalPattern: ['file1.txt', 'file2.txt', 'file3.txt'],
  zeroStepPattern: ['1', '2'],
}))

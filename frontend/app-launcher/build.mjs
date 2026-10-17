import { execFileSync } from 'node:child_process'
import { mkdir, realpath, writeFile } from 'node:fs/promises'
import { basename, dirname, relative, resolve, isAbsolute, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('.', import.meta.url))
const repository = await realpath(resolve(root, '../..'))
const output = process.argv[2]
if (!output || !output.endsWith('.tar.gz')) throw new Error('Provide an output .tar.gz path outside the repository')
const outside = target => { const path = relative(repository, target); return path === '..' || path.startsWith(`..${sep}`) || isAbsolute(path) }
if (!outside(resolve(output))) throw new Error('Build artifacts must stay outside the repository')
await mkdir(dirname(resolve(output)), { recursive: true })
const target = resolve(await realpath(dirname(resolve(output))), basename(output))
if (!outside(target)) throw new Error('Build artifacts must stay outside the repository')
const bundle = execFileSync('tar', ['--mtime=@0', '--owner=0', '--group=0', '--numeric-owner', '-czf', '-', 'index.html', 'atlas.css', 'navigation.mjs'], { cwd: root, maxBuffer: 2 * 1024 * 1024 })
await writeFile(target, bundle, { flag: 'wx', mode: 0o644 })
console.log(`Atlas launcher bundle: ${target} (${bundle.length} bytes)`)

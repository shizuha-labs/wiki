// Exercise the consumer's installed TipTap API, including both Markdown parsers.
import assert from 'node:assert/strict'
import { Worker } from 'node:worker_threads'
import { mergeAttributes } from '@tiptap/core'

const hostile = JSON.parse('{"__proto__":{"onerror":"unsafe()","data-inherited":"unexpected"}}')
const attributes = mergeAttributes({ title: 'Safe document', class: 'first' }, hostile, { class: 'second' })
assert.equal(attributes.onerror, undefined, 'untrusted attributes must not alter the result prototype')
assert.equal(attributes['data-inherited'], undefined)
assert.equal(attributes.title, 'Safe document')
assert.equal(attributes.class, 'first second')

const worker = new Worker(`
  const { parentPort } = require('node:worker_threads');
  (async () => {
    const { createAtomBlockMarkdownSpec, createInlineMarkdownSpec } = await import('@tiptap/core');
    const block = createAtomBlockMarkdownSpec({nodeName: 'acceptance'}).markdownTokenizer;
    const inline = createInlineMarkdownSpec({nodeName: 'acceptance', selfClosing: true}).markdownTokenizer;
    for (const value of ['__QUOTED_0'.repeat(8192), '-'.repeat(81920), 'title="safe"']) {
      if (!block.tokenize(':::acceptance {' + value + '} :::\\n', [], {})) throw Error('block parser lost valid token');
    }
    for (const value of ['0'.repeat(65536), '-'.repeat(65536), 'title="safe"']) {
      if (!inline.tokenize('[acceptance ' + value + ']', [], {})) throw Error('inline parser lost valid token');
    }
    parentPort.postMessage('passed');
  })().catch(error => { throw error });
`, { eval: true, execArgv: [] })
await new Promise((resolve, reject) => {
  const timeout = setTimeout(() => {
    worker.terminate()
    reject(new Error('Markdown attribute parser exceeded its bounded execution budget'))
  }, 1500)
  worker.once('message', message => {
    clearTimeout(timeout)
    assert.equal(message, 'passed')
    resolve()
  })
  worker.once('error', error => { clearTimeout(timeout); reject(error) })
})
await worker.terminate()
console.log('TipTap consumer prototype and bounded Markdown parser regressions passed')

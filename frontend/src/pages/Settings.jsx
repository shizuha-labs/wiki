import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { hydrateWikiMermaid } from '../utils/mermaidHydrate'
import {
  DIAGRAM_PACKS,
  activeDiagramPack,
  loadDiagramPrefs,
  resetDiagramPrefs,
  saveDiagramPrefs,
} from '../utils/diagramPrefs'

const PREVIEW = `flowchart LR
  you["You"] --> wiki["Wiki"]
  wiki --> id["ID"]
`

const fieldClass = 'mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-900 dark:text-white'
const labelClass = 'text-sm font-medium text-gray-700 dark:text-gray-300'

export default function Settings() {
  const { user } = useAuth()
  const [prefs, setPrefs] = useState(() => loadDiagramPrefs())
  const previewRef = useRef(null)

  function patch(partial) {
    setPrefs(saveDiagramPrefs(partial))
  }

  useEffect(() => {
    const root = previewRef.current
    if (!root) return
    root.setAttribute('data-mermaid-source', PREVIEW)
    root.removeAttribute('data-mermaid-done')
    const controller = new AbortController()
    hydrateWikiMermaid(root, { signal: controller.signal }).catch(() => {})
    return () => controller.abort()
  }, [prefs])

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>

      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Account</h2>

        <dl className="space-y-4">
          <div>
            <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Username</dt>
            <dd className="mt-1 text-gray-900 dark:text-white">{user?.username}</dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Email</dt>
            <dd className="mt-1 text-gray-900 dark:text-white">{user?.email}</dd>
          </div>
        </dl>

        <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            To manage your account settings, visit{' '}
            <a href="/id/settings" className="text-shizuha-600 hover:underline">
              Shizuha ID Settings
            </a>
          </p>
        </div>
      </div>

      <div id="diagrams" className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6 scroll-mt-24">
        <div className="flex items-start justify-between gap-4 mb-1">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Diagrams</h2>
          <button
            type="button"
            onClick={() => setPrefs(resetDiagramPrefs())}
            className="text-sm text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
          >
            Reset defaults
          </button>
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
          Saved to your account. They follow you across browsers and logins. Pages re-render as you change them.
        </p>

        <p className={`${labelClass} mb-2`}>Style</p>
        <div className="grid grid-cols-2 gap-2 mb-5 sm:grid-cols-4">
          {DIAGRAM_PACKS.map((pack) => {
            const active = activeDiagramPack(prefs) === pack.id
            return (
              <button
                key={pack.id}
                type="button"
                onClick={() => patch(pack.apply)}
                className={`rounded-lg border px-3 py-2 text-left ${
                  active
                    ? 'border-shizuha-500 bg-shizuha-50 text-gray-900 dark:border-sky-400 dark:bg-sky-950/40 dark:text-white'
                    : 'border-gray-200 bg-white text-gray-800 hover:border-gray-300 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100'
                }`}
              >
                <span className="block text-sm font-medium">{pack.label}</span>
                <span className="block text-xs text-gray-500 dark:text-gray-400">{pack.hint}</span>
              </button>
            )
          })}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className={labelClass}>Color scheme</span>
            <select className={fieldClass} value={prefs.scheme} onChange={(e) => patch({ scheme: e.target.value })}>
              <option value="match">Match wiki (dark / light)</option>
              <option value="whiteboard">Whiteboard paper (Excalidraw)</option>
              <option value="contrast">High contrast</option>
              <option value="dark">Dark</option>
              <option value="neutral">Neutral (classic light)</option>
              <option value="default">Mermaid default</option>
              <option value="forest">Forest</option>
            </select>
          </label>
          <label className="block">
            <span className={labelClass}>Look</span>
            <select className={fieldClass} value={prefs.look} onChange={(e) => patch({ look: e.target.value })}>
              <option value="classic">Classic (solid fills)</option>
              <option value="neo">Neo (3D bevel)</option>
              <option value="handDrawn">Hand-drawn (Excalidraw)</option>
            </select>
          </label>
          <label className="block">
            <span className={labelClass}>Corner radius</span>
            <select className={fieldClass} value={String(prefs.cornerRx)} onChange={(e) => patch({ cornerRx: Number(e.target.value) })}>
              <option value="0">Sharp (0)</option>
              <option value="4">Slight (4)</option>
              <option value="8">Rounded (8)</option>
              <option value="12">Soft (12)</option>
            </select>
          </label>
          <label className="block">
            <span className={labelClass}>Edges</span>
            <select className={fieldClass} value={prefs.curve} onChange={(e) => patch({ curve: e.target.value })}>
              <option value="basis">Smooth</option>
              <option value="linear">Straight</option>
              <option value="stepAfter">Stepped</option>
            </select>
          </label>
        </div>

        <div className="mt-5 space-y-3">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Opened diagrams match Excalidraw: scroll wheel zooms toward the cursor.
            Middle-mouse drag or Space-drag pans. Esc closes.
          </p>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              checked={prefs.openFullscreen}
              onChange={(e) => patch({ openFullscreen: e.target.checked })}
            />
            Open viewer in browser fullscreen
          </label>
        </div>

        <div className="mt-6">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-400 mb-2">Preview</p>
          <div ref={previewRef}>
            <div className="wiki-mermaid not-prose !my-0">{PREVIEW}</div>
          </div>
        </div>
      </div>
    </div>
  )
}

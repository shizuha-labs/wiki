// Wiki pages keep their Atlas fences. The Atlas application renders them.
export function hydrateWikiAtlas(container, { signal } = {}) {
  if (!container || signal?.aborted) return () => {}
  const cleanups = []
  for (const block of container.querySelectorAll('.wiki-atlas')) {
    const source = block.textContent || ''
    if (!source.trim()) continue
    const frame = document.createElement('iframe')
    frame.title = 'Atlas'
    frame.src = '/atlas/embed'
    frame.setAttribute('style', 'width:100%;height:72vh;border:0;border-radius:18px;background:transparent')
    const send = () => {
      frame.contentWindow?.postMessage(
        { type: 'shizuha-atlas-document', source },
        window.location.origin,
      )
    }
    const onMessage = event => {
      if (event.source !== frame.contentWindow) return
      if (event.origin !== window.location.origin) return
      if (event.data?.type === 'shizuha-atlas-embed-ready') send()
    }
    window.addEventListener('message', onMessage)
    frame.addEventListener('load', send)
    block.replaceChildren(frame)
    cleanups.push(() => {
      window.removeEventListener('message', onMessage)
      frame.remove()
    })
  }
  let cleaned = false
  const cleanup = () => {
    if (cleaned) return
    cleaned = true
    for (const fn of cleanups) fn()
  }
  signal?.addEventListener('abort', cleanup, { once: true })
  return cleanup
}

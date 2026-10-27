/** One render per comment id. Roots stay roots; replies stay nested. */
export function assembleCommentTree(comments) {
  const rows = Array.isArray(comments) ? comments : []
  const byId = new Map()
  for (const row of rows) {
    if (row?.id == null || byId.has(row.id)) continue
    byId.set(row.id, row)
  }
  const roots = []
  for (const row of byId.values()) {
    if (!row.parent) roots.push(row)
  }
  return roots.map((root) => {
    const nested = new Map()
    for (const reply of root.replies || []) {
      if (reply?.id != null && reply.id !== root.id) nested.set(reply.id, reply)
    }
    for (const row of byId.values()) {
      if (row.parent === root.id && row.id !== root.id) nested.set(row.id, row)
    }
    return { ...root, replies: [...nested.values()] }
  })
}

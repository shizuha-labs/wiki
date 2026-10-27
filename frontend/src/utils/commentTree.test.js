import { describe, expect, it } from 'vitest'
import { assembleCommentTree } from './commentTree'

describe('assembleCommentTree', () => {
  it('renders a reply once when the list also returns it as a root row', () => {
    const root = { id: 'root', parent: null, content: 'root', replies: [{ id: 'reply', parent: 'root', content: 'once' }] }
    const flatReply = { id: 'reply', parent: 'root', content: 'once', replies: [] }
    const tree = assembleCommentTree([root, flatReply])
    expect(tree).toHaveLength(1)
    expect(tree[0].replies.map((row) => row.id)).toEqual(['reply'])
    expect(tree.some((row) => row.id === 'reply')).toBe(false)
  })
})

import { Node, mergeAttributes } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import TableOfContentsComponent from './TableOfContentsComponent'

export const TableOfContents = Node.create({
  name: 'tableOfContents',

  group: 'block',

  atom: true,

  addAttributes() {
    return {
      levels: {
        default: [1, 2, 3],
        parseHTML: element => {
          const levels = element.getAttribute('data-toc-levels')
          return levels ? JSON.parse(levels) : [1, 2, 3]
        },
        renderHTML: attributes => ({
          'data-toc-levels': JSON.stringify(attributes.levels),
        }),
      },
    }
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-table-of-contents]',
      },
    ]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes(HTMLAttributes, { 'data-table-of-contents': '' }),
    ]
  },

  addNodeView() {
    return ReactNodeViewRenderer(TableOfContentsComponent)
  },

  addCommands() {
    return {
      insertTableOfContents:
        () =>
        ({ chain }) => {
          return chain()
            .insertContent({
              type: this.name,
              attrs: { levels: [1, 2, 3] },
            })
            .run()
        },
    }
  },
})

export default TableOfContents

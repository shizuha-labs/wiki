import { useState, useEffect, useCallback } from 'react'
import { NodeViewWrapper } from '@tiptap/react'
import { List } from 'lucide-react'

export default function TableOfContentsComponent({ editor, node }) {
  const [headings, setHeadings] = useState([])
  const levels = node.attrs.levels || [1, 2, 3]

  const extractHeadings = useCallback(() => {
    if (!editor) return []

    const items = []
    const doc = editor.state.doc

    doc.descendants((node, pos) => {
      if (node.type.name === 'heading') {
        const level = node.attrs.level
        if (levels.includes(level)) {
          const text = node.textContent
          const id = `heading-${pos}`
          items.push({ level, text, id, pos })
        }
      }
    })

    return items
  }, [editor, levels])

  useEffect(() => {
    if (!editor) return

    const updateHeadings = () => {
      setHeadings(extractHeadings())
    }

    // Initial extraction
    updateHeadings()

    // Listen for document changes
    editor.on('update', updateHeadings)

    return () => {
      editor.off('update', updateHeadings)
    }
  }, [editor, extractHeadings])

  const handleClick = (pos) => {
    if (!editor) return

    // Scroll to the heading position
    const domAtPos = editor.view.domAtPos(pos)
    if (domAtPos && domAtPos.node) {
      const element = domAtPos.node.nodeType === Node.TEXT_NODE
        ? domAtPos.node.parentElement
        : domAtPos.node
      element?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  return (
    <NodeViewWrapper className="toc-wrapper">
      <div
        className="table-of-contents bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-lg p-4 my-4"
        data-table-of-contents=""
        contentEditable={false}
      >
        <div className="flex items-center gap-2 mb-3 pb-2 border-b border-gray-200 dark:border-gray-700">
          <List className="h-4 w-4 text-gray-500 dark:text-gray-400" />
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
            Table of Contents
          </span>
        </div>

        {headings.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400 italic">
            No headings found. Add headings (H1, H2, H3) to your page to generate a table of contents.
          </p>
        ) : (
          <nav className="toc-nav">
            <ul className="space-y-1">
              {headings.map((heading, index) => (
                <li
                  key={index}
                  className={`toc-item toc-level-${heading.level}`}
                  style={{ paddingLeft: `${(heading.level - 1) * 16}px` }}
                >
                  <button
                    onClick={() => handleClick(heading.pos)}
                    className="text-sm text-shizuha-600 dark:text-shizuha-400 hover:underline text-left w-full truncate"
                  >
                    {heading.text || 'Untitled'}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </div>
    </NodeViewWrapper>
  )
}

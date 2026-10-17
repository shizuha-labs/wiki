import { Node, mergeAttributes } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import CalloutComponent from './CalloutComponent'

export const CALLOUT_TYPES = {
  info: {
    label: 'Info',
    icon: 'info',
    bgClass: 'bg-blue-50 dark:bg-blue-900/30',
    borderClass: 'border-blue-500',
    iconClass: 'text-blue-500',
  },
  note: {
    label: 'Note',
    icon: 'note',
    bgClass: 'bg-gray-50 dark:bg-gray-800',
    borderClass: 'border-gray-400',
    iconClass: 'text-gray-500',
  },
  tip: {
    label: 'Tip',
    icon: 'tip',
    bgClass: 'bg-green-50 dark:bg-green-900/30',
    borderClass: 'border-green-500',
    iconClass: 'text-green-500',
  },
  warning: {
    label: 'Warning',
    icon: 'warning',
    bgClass: 'bg-yellow-50 dark:bg-yellow-900/30',
    borderClass: 'border-yellow-500',
    iconClass: 'text-yellow-600',
  },
  error: {
    label: 'Error',
    icon: 'error',
    bgClass: 'bg-red-50 dark:bg-red-900/30',
    borderClass: 'border-red-500',
    iconClass: 'text-red-500',
  },
}

export const Callout = Node.create({
  name: 'callout',

  group: 'block',

  content: 'block+',

  defining: true,

  addAttributes() {
    return {
      type: {
        default: 'info',
        parseHTML: element => element.getAttribute('data-callout-type') || 'info',
        renderHTML: attributes => ({
          'data-callout-type': attributes.type,
        }),
      },
    }
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-callout]',
      },
    ]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes(HTMLAttributes, { 'data-callout': '' }),
      0,
    ]
  },

  addNodeView() {
    return ReactNodeViewRenderer(CalloutComponent)
  },

  addCommands() {
    return {
      setCallout:
        (type = 'info') =>
        ({ commands }) => {
          return commands.wrapIn(this.name, { type })
        },
      toggleCallout:
        (type = 'info') =>
        ({ commands }) => {
          return commands.toggleWrap(this.name, { type })
        },
      insertCallout:
        (type = 'info') =>
        ({ chain }) => {
          return chain()
            .insertContent({
              type: this.name,
              attrs: { type },
              content: [
                {
                  type: 'paragraph',
                },
              ],
            })
            .run()
        },
    }
  },
})

export default Callout

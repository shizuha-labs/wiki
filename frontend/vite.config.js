import { defineConfig, mergeConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createShizuhaConfig } from '@shizuha/ui/vite'

const basePath = process.env.VITE_BASE_PATH || '/'

export default mergeConfig(
  createShizuhaConfig({ port: 80, serviceName: 'wiki' }),
  defineConfig({
    plugins: [react()],
    resolve: {
      // Deduplicate ProseMirror and TipTap packages so the wiki frontend
      // and @shizuha/editor share one copy (prevents "Adding different
      // instances of a keyed plugin" error).
      dedupe: [
        '@tiptap/core',
        '@tiptap/pm',
        '@tiptap/react',
        '@tiptap/starter-kit',
        '@tiptap/extension-highlight',
        '@tiptap/extension-image',
        '@tiptap/extension-link',
        '@tiptap/extension-placeholder',
        '@tiptap/extension-table',
        '@tiptap/extension-table-cell',
        '@tiptap/extension-table-header',
        '@tiptap/extension-table-row',
        '@tiptap/extension-task-item',
        '@tiptap/extension-task-list',
        '@tiptap/extension-underline',
        'prosemirror-state',
        'prosemirror-model',
        'prosemirror-view',
        'prosemirror-transform',
        'prosemirror-keymap',
        'prosemirror-tables',
      ],
    },
    server: {
      proxy: basePath === '/' ? {
        '/api': {
          target: process.env.VITE_API_URL || 'http://localhost:8013',
          changeOrigin: true,
        },
      } : {},
    },
  })
)

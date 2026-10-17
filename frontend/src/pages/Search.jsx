import { useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useEditor, EditorContent } from '@tiptap/react'
import {
  createWikiExtensions,
  useEditorSync,
  Toolbar,
} from '@shizuha/editor'
import {
  Search as SearchIcon,
  FileText,
  BookOpen,
  ChevronLeft,
  PanelLeftClose,
  PanelLeftOpen,
  Maximize2,
  Minimize2,
} from 'lucide-react'
import { searchApi, pagesApi } from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatDistanceToNow } from 'date-fns'
import { cn } from '../utils/cn'
import { docToMarkdown } from '../utils/pageContent'

// Create extensions once at module level
const wikiExtensions = createWikiExtensions({ placeholder: 'Start writing...' })

/**
 * Evernote-style split-pane search for Wiki:
 *   LEFT:  search bar + persistent results list
 *   RIGHT: full page preview with editable TipTap editor + auto-save
 *
 * The results list stays visible while you click through pages.
 * No navigation away -- everything happens in this view.
 */
export default function Search() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [query, setQuery] = useState(searchParams.get('q') || '')
  const [debouncedQuery, setDebouncedQuery] = useState(query)
  const [selectedPageId, setSelectedPageId] = useState(null)
  const [showPreviewMobile, setShowPreviewMobile] = useState(false)
  const [panelCollapsed, setPanelCollapsed] = useState(false)
  const [maximized, setMaximized] = useState(false)
  const inputRef = useRef(null)

  // Sync query from URL params (when navigating from GlobalSearch bar)
  useEffect(() => {
    const urlQuery = searchParams.get('q') || ''
    if (urlQuery && urlQuery !== query) {
      setQuery(urlQuery)
      setDebouncedQuery(urlQuery)
      setSelectedPageId(null)
    }
  }, [searchParams]) // eslint-disable-line react-hooks/exhaustive-deps

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query)
      if (query) {
        setSearchParams({ q: query }, { replace: true })
      } else {
        setSearchParams({}, { replace: true })
      }
    }, 250)
    return () => clearTimeout(timer)
  }, [query, setSearchParams])

  // Search results
  const { data: results = [], isLoading } = useQuery({
    queryKey: ['wiki-search-split', debouncedQuery],
    queryFn: async () => {
      const response = await searchApi.search({ q: debouncedQuery })
      return response.data
    },
    enabled: !!debouncedQuery && debouncedQuery.length >= 2,
  })

  // Auto-select first result when results change
  useEffect(() => {
    if (results.length > 0 && !selectedPageId) {
      setSelectedPageId(results[0].id)
    }
  }, [results, selectedPageId])

  // Clear selection when query changes
  useEffect(() => {
    setSelectedPageId(null)
    setShowPreviewMobile(false)
  }, [debouncedQuery])

  // Keyboard navigation
  const handleKeyDown = useCallback((e) => {
    if (!results.length) return
    const currentIdx = results.findIndex(r => r.id === selectedPageId)

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      const next = Math.min(currentIdx + 1, results.length - 1)
      setSelectedPageId(results[next].id)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      const prev = Math.max(currentIdx - 1, 0)
      setSelectedPageId(results[prev].id)
    }
  }, [results, selectedPageId])

  // Highlight matching text
  const highlightMatches = (text, searchTerm) => {
    if (!text || !searchTerm) return text
    const parts = text.split(new RegExp(`(${searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'))
    return parts.map((part, i) =>
      part.toLowerCase() === searchTerm.toLowerCase()
        ? <mark key={i} className="bg-yellow-200 dark:bg-yellow-700/60 px-0.5 rounded">{part}</mark>
        : part
    )
  }

  // Get snippet with context around the match
  const getSnippet = (result) => {
    const text = result.excerpt || ''
    if (!debouncedQuery || !text) return text.slice(0, 120)
    const idx = text.toLowerCase().indexOf(debouncedQuery.toLowerCase())
    if (idx === -1) return text.slice(0, 120)
    const start = Math.max(0, idx - 40)
    const end = Math.min(text.length, idx + debouncedQuery.length + 80)
    return (start > 0 ? '...' : '') + text.slice(start, end) + (end < text.length ? '...' : '')
  }

  const handleSelectPage = (pageId) => {
    setSelectedPageId(pageId)
    setShowPreviewMobile(true)
  }

  return (
    <div className={cn(
      'flex flex-col',
      maximized ? 'fixed inset-0 z-50 bg-gray-50 dark:bg-gray-900 p-0' : 'h-[calc(100vh-12rem)] lg:h-[calc(100vh-9rem)]'
    )}>
      {/* Split pane container */}
      <div className={cn(
        'flex-1 flex overflow-hidden bg-white dark:bg-gray-800',
        maximized ? '' : 'rounded-lg border border-gray-200 dark:border-gray-700'
      )}>

        {/* LEFT: Search bar + results list */}
        <div className={cn(
          'flex flex-col border-r border-gray-200 dark:border-gray-700 transition-all duration-200',
          showPreviewMobile ? 'hidden lg:flex' : 'flex',
          panelCollapsed ? 'lg:w-0 lg:min-w-0 lg:overflow-hidden lg:border-r-0' : 'w-full lg:w-[380px] lg:min-w-[320px] lg:max-w-[420px]'
        )}>
          {/* Search input + panel controls */}
          <div className="p-3 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Search all pages..."
                  className="w-full pl-10 pr-3 py-2.5 text-sm border border-gray-200 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-700 focus:bg-white dark:focus:bg-gray-700 focus:ring-2 focus:ring-shizuha-500 focus:border-transparent text-gray-900 dark:text-gray-100"
                  autoFocus
                />
              </div>
              {/* Collapse results panel */}
              <button
                onClick={() => setPanelCollapsed(true)}
                className="hidden lg:block p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 flex-shrink-0"
                title="Hide search results"
              >
                <PanelLeftClose className="h-4 w-4" />
              </button>
            </div>
            {debouncedQuery && (
              <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                {results.length} result{results.length !== 1 ? 's' : ''} for "{debouncedQuery}"
              </p>
            )}
          </div>

          {/* Results list */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center h-32">
                <LoadingSpinner />
              </div>
            ) : results.length > 0 ? (
              results.map((result) => (
                <button
                  key={result.id}
                  onClick={() => handleSelectPage(result.id)}
                  className={cn(
                    'w-full text-left px-4 py-3 border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors',
                    selectedPageId === result.id && 'bg-shizuha-50 dark:bg-shizuha-900/20 border-l-2 border-l-shizuha-500'
                  )}
                >
                  <h4 className="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {highlightMatches(result.title || 'Untitled', debouncedQuery)}
                  </h4>
                  <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2 mt-1">
                    {highlightMatches(getSnippet(result), debouncedQuery)}
                  </p>
                  <div className="flex items-center gap-2 mt-1.5">
                    {result.space_name && (
                      <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-gray-500 dark:text-gray-400 truncate max-w-[150px]">
                        <BookOpen className="h-2.5 w-2.5 flex-shrink-0" />
                        {result.space_name}
                      </span>
                    )}
                    <span className="text-[10px] text-gray-400 dark:text-gray-500">
                      {formatDistanceToNow(new Date(result.updated_at), { addSuffix: true })}
                    </span>
                  </div>
                  {result.labels?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {result.labels.map((label) => (
                        <span
                          key={label.id}
                          className="px-1.5 py-0.5 text-[10px] rounded-full"
                          style={{ backgroundColor: label.color + '20', color: label.color }}
                        >
                          {label.name}
                        </span>
                      ))}
                    </div>
                  )}
                </button>
              ))
            ) : debouncedQuery ? (
              <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                <FileText className="mx-auto h-10 w-10 text-gray-300 dark:text-gray-600" />
                <p className="mt-3 text-sm">No pages found</p>
                <p className="text-xs mt-1">Try a different search term</p>
              </div>
            ) : (
              <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                <SearchIcon className="mx-auto h-10 w-10 text-gray-300 dark:text-gray-600" />
                <p className="mt-3 text-sm">Search your wiki</p>
                <p className="text-xs mt-1">Results appear as you type</p>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT: Editable page (like Evernote -- edit directly from search) */}
        <PagePane
          pageId={selectedPageId}
          showPreviewMobile={showPreviewMobile}
          setShowPreviewMobile={setShowPreviewMobile}
          resultsExist={results.length > 0}
          panelCollapsed={panelCollapsed}
          setPanelCollapsed={setPanelCollapsed}
          maximized={maximized}
          setMaximized={setMaximized}
        />
      </div>
    </div>
  )
}

/**
 * Right pane: editable wiki page with TipTap editor + auto-save.
 * Separated as its own component so the editor remounts on page change.
 */
function PagePane({ pageId, showPreviewMobile, setShowPreviewMobile, resultsExist, panelCollapsed, setPanelCollapsed, maximized, setMaximized }) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const [hasChanges, setHasChanges] = useState(false)
  const saveTimerRef = useRef(null)
  const lastSavedContentRef = useRef(null)
  const lastSavedTitleRef = useRef(null)

  // Fetch full page
  const { data: page, isLoading } = useQuery({
    queryKey: ['wiki-page-preview', pageId],
    queryFn: async () => {
      const response = await pagesApi.get(pageId)
      return response.data
    },
    enabled: !!pageId,
  })

  // TipTap editor
  const editor = useEditor({
    extensions: wikiExtensions,
    content: '',
    editorProps: {
      attributes: {
        class: 'prose dark:prose-invert max-w-none focus:outline-none min-h-[400px] px-6 py-4',
      },
    },
    onUpdate: ({ editor: ed }) => {
      setHasChanges(true)
      scheduleSave(ed)
    },
  })

  // Init state from page
  useEffect(() => {
    if (page) {
      setTitle(page.title || '')
      setHasChanges(false)
      lastSavedContentRef.current = JSON.stringify(page.content_json)
      lastSavedTitleRef.current = page.title
    }
  }, [page])

  // Sync content to editor
  useEditorSync(editor, page?.content_json)

  // Auto-save mutation
  const saveMutation = useMutation({
    mutationFn: ({ pageId: pid, data }) => pagesApi.update(pid, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wiki-search-split'] })
      setHasChanges(false)
    },
  })

  // Schedule auto-save with 1.5s debounce
  const scheduleSave = useCallback((ed) => {
    if (!pageId) return
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      if (!ed || ed.isDestroyed) return
      const contentJson = ed.getJSON()
      // WIKI-120: serialize the doc to Markdown (getText() flattens headings/fences).
      const contentText = docToMarkdown(contentJson)
      const currentContentStr = JSON.stringify(contentJson)

      // Only save if content or title actually changed
      if (currentContentStr !== lastSavedContentRef.current || title !== lastSavedTitleRef.current) {
        lastSavedContentRef.current = currentContentStr
        lastSavedTitleRef.current = title
        saveMutation.mutate({
          pageId,
          data: {
            title: title.trim() || 'Untitled',
            content_json: contentJson,
            content_text: contentText,
          },
        })
      }
    }, 1500)
  }, [pageId, title, saveMutation])

  // Also trigger save on title change
  useEffect(() => {
    if (!pageId || !editor || !page) return
    if (title !== lastSavedTitleRef.current) {
      setHasChanges(true)
      scheduleSave(editor)
    }
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }
  }, [title]) // eslint-disable-line react-hooks/exhaustive-deps

  // Cleanup timer on unmount
  useEffect(() => {
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }
  }, [])

  // Word count
  const wordCount = editor ? editor.getText().split(/\s+/).filter(Boolean).length : 0

  return (
    <div className={cn(
      'flex-1 flex flex-col overflow-hidden',
      !showPreviewMobile ? 'hidden lg:flex' : 'flex'
    )}>
      {pageId && page ? (
        <>
          {/* Header */}
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 flex items-center gap-3">
            {/* Mobile back button */}
            <button
              onClick={() => setShowPreviewMobile(false)}
              className="lg:hidden p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500"
            >
              <ChevronLeft className="h-5 w-5" />
            </button>

            {/* Show results panel button (when collapsed) */}
            {panelCollapsed && (
              <button
                onClick={() => setPanelCollapsed(false)}
                className="hidden lg:block p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500"
                title="Show search results"
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            )}

            <div className="flex-1 min-w-0">
              <input
                type="text"
                value={title}
                onChange={(e) => { setTitle(e.target.value); setHasChanges(true) }}
                className="w-full text-lg font-semibold text-gray-900 dark:text-white bg-transparent border-none outline-none focus:ring-0 p-0"
                placeholder="Untitled"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {page.space_name && (
                  <span className="inline-flex items-center gap-1">
                    <BookOpen className="h-3 w-3" />
                    {page.space_name} ·{' '}
                  </span>
                )}
                {wordCount} words
                {hasChanges && saveMutation.isPending && <span className="text-orange-500 ml-2">· Saving...</span>}
                {!hasChanges && saveMutation.isSuccess && <span className="text-green-500 ml-2">· Saved</span>}
              </p>
            </div>

            {/* Maximize / minimize */}
            <button
              onClick={() => setMaximized(!maximized)}
              className="hidden lg:block p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              title={maximized ? 'Exit full screen' : 'Full screen'}
            >
              {maximized ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
          </div>

          {/* Toolbar */}
          {editor && (
            <div className="border-b border-gray-200 dark:border-gray-700">
              <Toolbar editor={editor} preset="wiki" />
            </div>
          )}

          {/* TipTap editor */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center h-32">
                <LoadingSpinner />
              </div>
            ) : (
              <EditorContent editor={editor} />
            )}
          </div>
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-500">
          <div className="text-center">
            <FileText className="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
            <p className="mt-3 text-sm">
              {resultsExist ? 'Select a page to edit' : 'Search to find pages'}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

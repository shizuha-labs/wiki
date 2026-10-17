import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search, FileText, BookOpen, Command } from 'lucide-react'
import { searchApi } from '../services/api'
import { formatDistanceToNow } from 'date-fns'

export default function GlobalSearch() {
  const [query, setQuery] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef(null)
  const containerRef = useRef(null)
  const navigate = useNavigate()

  // Debounce
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 200)
    return () => clearTimeout(timer)
  }, [query])

  // Live search
  const { data: results = [] } = useQuery({
    queryKey: ['global-search', debouncedQuery],
    queryFn: async () => {
      const response = await searchApi.search({ q: debouncedQuery, page_size: 8 })
      return response.data
    },
    enabled: !!debouncedQuery && debouncedQuery.length >= 2,
  })

  // Keyboard shortcut: Cmd+K or Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
        setIsOpen(true)
      }
      if (e.key === 'Escape') {
        setIsOpen(false)
        inputRef.current?.blur()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Click outside to close
  useEffect(() => {
    const handleClick = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Keyboard navigation in results
  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && query.trim()) {
      e.preventDefault()
      navigate(`/search?q=${encodeURIComponent(query.trim())}`)
      setIsOpen(false)
      setQuery('')
      return
    }

    if (!isOpen || results.length === 0) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(i => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(i => Math.max(i - 1, 0))
    }
  }, [isOpen, results, navigate, query])

  // Reset selection when results change
  useEffect(() => { setSelectedIndex(0) }, [results])

  const handleResultClick = () => {
    navigate(`/search?q=${encodeURIComponent(query)}`)
    setIsOpen(false)
    setQuery('')
  }

  // Snippet from excerpt
  const getSnippet = (result) => {
    const text = result.excerpt || ''
    if (!debouncedQuery || !text) return text.slice(0, 100)
    const idx = text.toLowerCase().indexOf(debouncedQuery.toLowerCase())
    if (idx === -1) return text.slice(0, 100)
    const start = Math.max(0, idx - 30)
    const end = Math.min(text.length, idx + debouncedQuery.length + 70)
    return (start > 0 ? '...' : '') + text.slice(start, end) + (end < text.length ? '...' : '')
  }

  return (
    <div ref={containerRef} className="relative w-full max-w-2xl mx-auto">
      {/* Search input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setIsOpen(true) }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search wiki pages..."
          className="w-full pl-10 pr-20 py-2 text-sm border border-gray-200 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-700/50 focus:bg-white dark:focus:bg-gray-700 focus:ring-2 focus:ring-shizuha-500 focus:border-transparent text-gray-900 dark:text-gray-100 placeholder-gray-400 transition-colors"
        />
        {/* Shortcut hint */}
        <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1">
          {!query && (
            <kbd className="hidden sm:inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-medium text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-600 rounded border border-gray-200 dark:border-gray-500">
              <Command className="h-2.5 w-2.5" />K
            </kbd>
          )}
        </div>
      </div>

      {/* Results dropdown */}
      {isOpen && debouncedQuery.length >= 2 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-xl z-50 max-h-[400px] overflow-y-auto">
          {results.length > 0 ? (
            <>
              {results.slice(0, 8).map((result, idx) => (
                <button
                  key={result.id}
                  onClick={() => handleResultClick()}
                  className={`w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 border-b border-gray-100 dark:border-gray-700/50 last:border-0 transition-colors ${
                    idx === selectedIndex ? 'bg-shizuha-50 dark:bg-shizuha-900/20' : ''
                  }`}
                >
                  <FileText className="h-4 w-4 text-gray-400 mt-0.5 flex-shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                      {result.title || 'Untitled'}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2 mt-0.5">
                      {getSnippet(result)}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      {result.space_name && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-gray-500 dark:text-gray-400">
                          <BookOpen className="h-2.5 w-2.5" />
                          {result.space_name}
                        </span>
                      )}
                      <span className="text-[10px] text-gray-400 dark:text-gray-500">
                        {formatDistanceToNow(new Date(result.updated_at), { addSuffix: true })}
                      </span>
                    </div>
                  </div>
                </button>
              ))}
              {results.length > 8 && (
                <button
                  onClick={() => { navigate(`/search?q=${encodeURIComponent(debouncedQuery)}`); setIsOpen(false); setQuery('') }}
                  className="w-full px-4 py-2.5 text-center text-sm text-shizuha-600 dark:text-shizuha-400 hover:bg-gray-50 dark:hover:bg-gray-700/50 font-medium"
                >
                  View all {results.length} results
                </button>
              )}
            </>
          ) : (
            <div className="px-4 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
              No pages found for "{debouncedQuery}"
            </div>
          )}
        </div>
      )}
    </div>
  )
}

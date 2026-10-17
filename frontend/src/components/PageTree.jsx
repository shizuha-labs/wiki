import { useState, useEffect, useCallback, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileText, ChevronRight, GripVertical, MoreHorizontal, Edit, Trash2 } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { pagesApi } from '../services/api'

/**
 * Find the path of ancestor IDs from root to a node matching the given slug.
 * Returns an array of page IDs that should be expanded, or empty if not found.
 */
function findPathToSlug(pages, targetSlug) {
  for (const page of pages) {
    if (page.slug === targetSlug) {
      return [page.id]
    }
    if (page.children?.length > 0) {
      const childPath = findPathToSlug(page.children, targetSlug)
      if (childPath.length > 0) {
        return [page.id, ...childPath]
      }
    }
  }
  return []
}

export default function PageTree({ pages, spaceKey, currentSlug, compact = false, enableDragDrop = false, permissions = null }) {
  // Compute which nodes to auto-expand (path to current page)
  const [expanded, setExpanded] = useState({})
  const [initialized, setInitialized] = useState(false)

  useEffect(() => {
    if (!pages || pages.length === 0) return

    if (currentSlug) {
      const path = findPathToSlug(pages, currentSlug)
      if (path.length > 0) {
        const expandMap = {}
        path.forEach(id => { expandMap[id] = true })
        setExpanded(prev => ({ ...prev, ...expandMap }))
      }
    }

    // On first load without a currentSlug, expand root level
    if (!initialized && !currentSlug) {
      const expandMap = {}
      pages.forEach(p => { expandMap[p.id] = true })
      setExpanded(expandMap)
    }
    setInitialized(true)
  }, [pages, currentSlug])

  const toggleExpand = useCallback((pageId) => {
    setExpanded(prev => ({ ...prev, [pageId]: !prev[pageId] }))
  }, [])

  return (
    <PageTreeLevel
      pages={pages}
      spaceKey={spaceKey}
      currentSlug={currentSlug}
      compact={compact}
      level={0}
      expanded={expanded}
      toggleExpand={toggleExpand}
      enableDragDrop={enableDragDrop}
      permissions={permissions}
    />
  )
}

function PageTreeLevel({ pages, spaceKey, currentSlug, compact, level, expanded, toggleExpand, enableDragDrop, permissions }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [dragOverId, setDragOverId] = useState(null)
  const [dropPosition, setDropPosition] = useState(null) // 'above', 'below', 'child'
  const [menuOpenId, setMenuOpenId] = useState(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState(null)
  const [deleteTitle, setDeleteTitle] = useState('')
  const dragItem = useRef(null)
  const menuRef = useRef(null)

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpenId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const moveMutation = useMutation({
    mutationFn: ({ id, data }) => pagesApi.movePage(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['space', spaceKey, 'tree'] })
    },
  })

  const reorderMutation = useMutation({
    mutationFn: (data) => pagesApi.reorderPages(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['space', spaceKey, 'tree'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => pagesApi.delete(id),
    onSuccess: () => {
      setDeleteConfirmId(null)
      queryClient.invalidateQueries({ queryKey: ['space', spaceKey, 'tree'] })
      queryClient.invalidateQueries({ queryKey: ['pages'] })
    },
    onError: (error) => {
      setDeleteConfirmId(null)
      const msg = error.response?.status === 403
        ? (error.response.data?.detail || "You don't have permission to delete this page.")
        : 'Failed to delete page. Please try again.'
      alert(msg)
    },
  })

  const handleDragStart = (e, page) => {
    dragItem.current = page
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', page.id)
  }

  const handleDragOver = (e, page) => {
    e.preventDefault()
    e.stopPropagation()
    if (!dragItem.current || dragItem.current.id === page.id) return

    const rect = e.currentTarget.getBoundingClientRect()
    const y = e.clientY - rect.top
    const height = rect.height

    if (y < height * 0.25) {
      setDropPosition('above')
    } else if (y > height * 0.75) {
      setDropPosition('below')
    } else {
      setDropPosition('child')
    }
    setDragOverId(page.id)
  }

  const handleDragLeave = (e) => {
    // Only clear if we're actually leaving the element
    if (!e.currentTarget.contains(e.relatedTarget)) {
      setDragOverId(null)
      setDropPosition(null)
    }
  }

  const handleDrop = (e, targetPage, siblingPages) => {
    e.preventDefault()
    e.stopPropagation()
    const dragged = dragItem.current
    if (!dragged || dragged.id === targetPage.id) {
      setDragOverId(null)
      setDropPosition(null)
      return
    }

    if (dropPosition === 'child') {
      // Move as child of target
      moveMutation.mutate({ id: dragged.id, data: { parent: targetPage.id, position: 0 } })
    } else {
      // Reorder among siblings
      const ids = siblingPages.map(p => p.id).filter(id => id !== dragged.id)
      const targetIndex = ids.indexOf(targetPage.id)
      const insertIndex = dropPosition === 'above' ? targetIndex : targetIndex + 1
      ids.splice(insertIndex, 0, dragged.id)
      reorderMutation.mutate({ page_ids: ids })
    }

    dragItem.current = null
    setDragOverId(null)
    setDropPosition(null)
  }

  const handleDragEnd = () => {
    dragItem.current = null
    setDragOverId(null)
    setDropPosition(null)
  }

  const textSize = compact ? 'text-sm' : 'text-sm'
  const py = compact ? 'py-1' : 'py-1.5'
  const ml = level > 0 ? 'ml-4' : ''

  return (
    <>
      <ul className={`space-y-0.5 ${ml} ${level > 0 ? 'mt-0.5' : ''}`}>
        {pages.map((page) => {
          const hasChildren = page.children?.length > 0
          const isExpanded = expanded[page.id] ?? false
          const isCurrent = currentSlug && page.slug === currentSlug
          const isDragOver = dragOverId === page.id
          const isMenuOpen = menuOpenId === page.id

          let dropIndicatorClass = ''
          if (isDragOver && enableDragDrop) {
            if (dropPosition === 'above') dropIndicatorClass = 'border-t-2 border-shizuha-500'
            else if (dropPosition === 'below') dropIndicatorClass = 'border-b-2 border-shizuha-500'
            else if (dropPosition === 'child') dropIndicatorClass = 'bg-shizuha-50 dark:bg-shizuha-900/30'
          }

          return (
            <li key={page.id} className="group">
              <div
                className={`flex items-center gap-0.5 ${dropIndicatorClass} rounded`}
                onDragOver={enableDragDrop ? (e) => handleDragOver(e, page) : undefined}
                onDragLeave={enableDragDrop ? handleDragLeave : undefined}
                onDrop={enableDragDrop ? (e) => handleDrop(e, page, pages) : undefined}
              >
                {enableDragDrop && (
                  <span
                    draggable
                    onDragStart={(e) => handleDragStart(e, page)}
                    onDragEnd={handleDragEnd}
                    className="cursor-grab active:cursor-grabbing p-0.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                  >
                    <GripVertical className="h-3.5 w-3.5" />
                  </span>
                )}
                {hasChildren ? (
                  <button
                    onClick={() => toggleExpand(page.id)}
                    className="p-0.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded flex-shrink-0"
                  >
                    <ChevronRight
                      className={`h-4 w-4 text-gray-400 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                    />
                  </button>
                ) : (
                  <span className="w-5 flex-shrink-0" />
                )}
                <Link
                  to={`/spaces/${spaceKey}/pages/${page.slug}`}
                  className={`flex-1 flex items-center gap-2 px-2 ${py} rounded transition-colors truncate ${textSize} ${
                    isCurrent
                      ? 'bg-shizuha-50 dark:bg-shizuha-900/50 text-shizuha-700 dark:text-shizuha-300 font-medium'
                      : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                  }`}
                >
                  <FileText className={`${compact ? 'h-3.5 w-3.5' : 'h-4 w-4'} text-gray-400 flex-shrink-0`} />
                  <span className="truncate">{page.title}</span>
                  {page.status === 'draft' && (
                    <span className="text-xs px-1.5 py-0.5 bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300 rounded flex-shrink-0">
                      Draft
                    </span>
                  )}
                </Link>
                {/* Three-dot action menu */}
                <div className="relative flex-shrink-0" ref={isMenuOpen ? menuRef : undefined}>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setMenuOpenId(isMenuOpen ? null : page.id)
                    }}
                    className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 rounded opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </button>
                  {isMenuOpen && (
                    <div className="absolute right-0 mt-1 w-40 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-20">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          setMenuOpenId(null)
                          navigate(`/spaces/${spaceKey}/pages/${page.slug}/edit`)
                        }}
                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
                      >
                        <Edit className="h-4 w-4" />
                        Edit
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          setMenuOpenId(null)
                          setDeleteTitle(page.title)
                          setDeleteConfirmId(page.id)
                        }}
                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                      >
                        <Trash2 className="h-4 w-4" />
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>
              {hasChildren && isExpanded && (
                <PageTreeLevel
                  pages={page.children}
                  spaceKey={spaceKey}
                  currentSlug={currentSlug}
                  compact={compact}
                  level={level + 1}
                  expanded={expanded}
                  toggleExpand={toggleExpand}
                  enableDragDrop={enableDragDrop}
                  permissions={permissions}
                />
              )}
            </li>
          )
        })}
      </ul>

      {/* Delete confirmation modal */}
      {deleteConfirmId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Delete page</h3>
            <p className="text-gray-600 dark:text-gray-400 mb-1">
              Are you sure you want to delete <strong>"{deleteTitle}"</strong>?
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-500 mb-6">
              This will permanently delete the page, all its versions, comments, and attachments. This action cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteConfirmId(null)}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate(deleteConfirmId)}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

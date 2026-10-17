import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { Edit, ChevronRight, Clock, Eye, MessageSquare, Paperclip, History, Send, ChevronDown, MoreHorizontal, Trash2, Link2, Network, Maximize2, Minimize2 } from 'lucide-react'
import { pagesApi, commentsApi, attachmentsApi } from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'
import { AttachmentPanel } from '../components/attachments'
import { formatDistanceToNow, format } from 'date-fns'
import { useAuth } from '../contexts/AuthContext'
import { attachmentIdFromMediaSrc, markdownHeadings, renderMarkdownContent, renderSafeImageTag, renderTableOfContents, sanitizePageContent, shouldRenderMarkdown, tipTapHeadings, WIKI_MERMAID_CLASS, renderAtlasPlaceholder } from '../utils/pageContent'
import { hydrateWikiMermaid } from '../utils/mermaidHydrate'
import { DIAGRAM_PREFS_EVENT } from '../utils/diagramPrefs'

export default function PageView() {
  const { spaceKey, pageSlug } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showVersions, setShowVersions] = useState(false)
  const [showComments, setShowComments] = useState(true)
  const [showAttachments, setShowAttachments] = useState(false)
  const [showBacklinks, setShowBacklinks] = useState(false)
  const [showRelated, setShowRelated] = useState(true)
  const [showActions, setShowActions] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [zen, setZen] = useState(false)
  const actionsRef = useRef(null)
  const contentRef = useRef(null)

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (actionsRef.current && !actionsRef.current.contains(e.target)) {
        setShowActions(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const deleteMutation = useMutation({
    mutationFn: () => pagesApi.delete(page.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pages'] })
      queryClient.invalidateQueries({ queryKey: ['space'] })
      navigate(`/spaces/${spaceKey}`)
    },
    onError: (error) => {
      setShowDeleteConfirm(false)
      if (error.response?.status === 403) {
        const msg = error.response.data?.detail || "You don't have permission to delete this page."
        alert(msg)
      }
    },
  })

  // Fetch page details
  const { data: page, isLoading } = useQuery({
    queryKey: ['page', spaceKey, pageSlug],
    queryFn: async () => {
      // First get pages by space and slug
      const response = await pagesApi.list({ space_key: spaceKey, slug: pageSlug })
      const pages = response.data.results || response.data
      if (pages.length > 0) {
        // Fetch full details
        const detailResponse = await pagesApi.get(pages[0].id)
        return detailResponse.data
      }
      return null
    },
  })

  const [themeTick, setThemeTick] = useState(0)
  useEffect(() => {
    const root = contentRef.current
    if (!root?.querySelector('.wiki-atlas')) return undefined
    const controller = new AbortController()
    let cleanup = () => {}
    import('../utils/atlasHydrate').then(({ hydrateWikiAtlas }) => {
      if (!controller.signal.aborted) cleanup = hydrateWikiAtlas(root, { signal: controller.signal })
    }).catch(() => {})
    return () => { controller.abort(); cleanup() }
  }, [page?.id, page?.updated_at, page?.content_json, page?.content_text, zen])
  useEffect(() => {
    const html = document.documentElement
    const bump = () => setThemeTick((n) => n + 1)
    const observer = new MutationObserver(bump)
    observer.observe(html, { attributes: true, attributeFilter: ['class'] })
    window.addEventListener(DIAGRAM_PREFS_EVENT, bump)
    return () => {
      observer.disconnect()
      window.removeEventListener(DIAGRAM_PREFS_EVENT, bump)
    }
  }, [])

  useEffect(() => {
    const root = contentRef.current
    if (!root) return undefined
    const controller = new AbortController()
    hydrateWikiMermaid(root, { signal: controller.signal }).catch(() => {})
    return () => controller.abort()
  }, [page?.id, page?.updated_at, page?.content_text, page?.content_json, zen, themeTick])

  // <img src="/wiki/api/attachments/…/view/"> is an unauthenticated GET.
  // Private pages 404 that request. Fetch with the session and swap in a blob.
  useEffect(() => {
    const root = contentRef.current
    if (!root) return undefined
    let cancelled = false
    const urls = []
    root.querySelectorAll('img').forEach((img) => {
      const id = attachmentIdFromMediaSrc(img.getAttribute('src'))
      if (!id) return
      attachmentsApi.view(id).then((res) => {
        if (cancelled) return
        const url = URL.createObjectURL(res.data)
        urls.push(url)
        img.src = url
      }).catch(() => {})
    })
    return () => {
      cancelled = true
      urls.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [page?.id, page?.updated_at, page?.content_text, page?.content_json, zen])

  const exitZen = () => {
    setZen(false)
    document.documentElement.classList.remove('wiki-zen')
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {})
    }
  }

  const enterZen = () => {
    setZen(true)
    document.documentElement.classList.add('wiki-zen')
    const root = document.documentElement
    if (root.requestFullscreen) {
      root.requestFullscreen().catch(() => {})
    }
  }

  useEffect(() => {
    const onFullscreen = () => {
      if (!document.fullscreenElement) {
        document.documentElement.classList.remove('wiki-zen')
        setZen(false)
      }
    }
    document.addEventListener('fullscreenchange', onFullscreen)
    return () => {
      document.removeEventListener('fullscreenchange', onFullscreen)
      document.documentElement.classList.remove('wiki-zen')
    }
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  const renderMarkdown = page && shouldRenderMarkdown(page.content_json, page.content_text)
  const renderedHeadings = page
    ? (renderMarkdown ? markdownHeadings(page.content_text) : tipTapHeadings(page.content_json))
    : []

  if (!page) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Page not found</h2>
        <Link to={`/spaces/${spaceKey}`} className="text-shizuha-600 hover:underline mt-2 inline-block">
          Back to space
        </Link>
      </div>
    )
  }

  return (
    <div className={zen ? 'max-w-6xl mx-auto' : 'max-w-4xl mx-auto'}>
      {zen && (
        <button
          type="button"
          onClick={exitZen}
          className="fixed top-4 right-4 z-50 flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-900/85 text-white text-sm hover:bg-gray-900"
          title="Exit zen (Esc)"
        >
          <Minimize2 className="h-4 w-4" />
          Exit zen
        </button>
      )}
      {/* Breadcrumbs */}
      {!zen && (
      <nav className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-4">
        <Link to="/spaces" className="hover:text-shizuha-600">Spaces</Link>
        <ChevronRight className="h-4 w-4" />
        <Link to={`/spaces/${spaceKey}`} className="hover:text-shizuha-600">{page.space_name}</Link>
        {page.breadcrumbs?.slice(0, -1).map((crumb) => (
          <span key={crumb.id} className="flex items-center gap-2">
            <ChevronRight className="h-4 w-4" />
            <Link to={`/spaces/${spaceKey}/pages/${crumb.slug}`} className="hover:text-shizuha-600">
              {crumb.title}
            </Link>
          </span>
        ))}
      </nav>
      )}

      {/* Page header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">{page.title}</h1>
          <div className="flex items-center gap-4 mt-2 text-sm text-gray-500 dark:text-gray-400">
            <span className="flex items-center gap-1">
              <Clock className="h-4 w-4" />
              Updated {formatDistanceToNow(new Date(page.updated_at), { addSuffix: true })}
            </span>
            <span className="flex items-center gap-1">
              <Eye className="h-4 w-4" />
              {page.view_count} views
            </span>
            {page.comments_count > 0 && (
              <span className="flex items-center gap-1">
                <MessageSquare className="h-4 w-4" />
                {page.comments_count} comments
              </span>
            )}
            {page.attachments_count > 0 && (
              <span className="flex items-center gap-1">
                <Paperclip className="h-4 w-4" />
                {page.attachments_count} attachments
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!zen && (
          <button
            type="button"
            onClick={enterZen}
            className="flex items-center gap-2 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
            title="Zen / fullscreen"
          >
            <Maximize2 className="h-4 w-4" />
            Zen
          </button>
          )}
          {!zen && (
          <button
            onClick={() => navigate(`/spaces/${spaceKey}/pages/${pageSlug}/edit`)}
            className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700"
          >
            <Edit className="h-4 w-4" />
            Edit
          </button>
          )}
          {!zen && (
          <div className="relative" ref={actionsRef}>
            <button
              onClick={() => setShowActions(!showActions)}
              className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
            >
              <MoreHorizontal className="h-5 w-5" />
            </button>
            {showActions && (
              <div className="absolute right-0 mt-1 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-10">
                <button
                  onClick={() => {
                    setShowActions(false)
                    setShowDeleteConfirm(true)
                  }}
                  className="w-full flex items-center gap-2 px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete page
                </button>
              </div>
            )}
          </div>
          )}
        </div>
      </div>

      {/* Delete confirmation modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Delete page</h3>
            <p className="text-gray-600 dark:text-gray-400 mb-1">
              Are you sure you want to delete <strong>"{page.title}"</strong>?
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-500 mb-6">
              This will permanently delete the page, all its versions, comments, and attachments. This action cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate()}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
              </button>
            </div>
            {deleteMutation.isError && (
              <p className="mt-3 text-sm text-red-600 dark:text-red-400">
                {deleteMutation.error?.response?.data?.detail || 'Failed to delete page. Please try again.'}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Labels */}
      {page.labels?.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-6">
          {page.labels.map((label) => (
            <Link
              key={label.id}
              to={`/spaces/${spaceKey}/labels/${label.id}`}
              className="px-2 py-1 text-xs rounded-full hover:ring-2 hover:ring-shizuha-300"
              style={{ backgroundColor: label.color + '20', color: label.color }}
            >
              {label.name}
            </Link>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
        <div
          ref={contentRef}
          className="prose dark:prose-invert max-w-none"
          dangerouslySetInnerHTML={{
            __html: renderMarkdown
              ? renderMarkdownContent(page.content_text)
              : renderContent(page.content_json),
          }}
        />
        {renderedHeadings.length > 1 && (
          <div
            className="mt-8 pt-6 border-t border-gray-200 dark:border-gray-700"
            dangerouslySetInnerHTML={{ __html: renderTableOfContents(renderedHeadings) }}
          />
        )}
      </div>

      {/* Child pages */}
      {!zen && page.children_count > 0 && (
        <div className="mt-8">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Child Pages</h2>
          <ChildPages pageId={page.id} spaceKey={spaceKey} />
        </div>
      )}

      {/* Version History */}
      {!zen && (
      <div className="mt-8">
        <button
          onClick={() => setShowVersions(!showVersions)}
          className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white mb-4 hover:text-shizuha-600"
        >
          <History className="h-5 w-5" />
          Version History
          <ChevronDown className={`h-4 w-4 transition-transform ${showVersions ? 'rotate-180' : ''}`} />
        </button>
        {showVersions && <PageVersions pageId={page.id} />}
      </div>
      )}

      {/* Attachments */}
      {!zen && (
      <div className="mt-8">
        <button
          onClick={() => setShowAttachments(!showAttachments)}
          className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white mb-4 hover:text-shizuha-600"
        >
          <Paperclip className="h-5 w-5" />
          Attachments ({page.attachments_count || 0})
          <ChevronDown className={`h-4 w-4 transition-transform ${showAttachments ? 'rotate-180' : ''}`} />
        </button>
        {showAttachments && (
          <AttachmentPanel
            pageId={page.id}
            readOnly
            defaultExpanded={true}
          />
        )}
      </div>
      )}

      {/* Comments */}
      {!zen && (
      <div className="mt-8">
        <button
          onClick={() => setShowComments(!showComments)}
          className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white mb-4 hover:text-shizuha-600"
        >
          <MessageSquare className="h-5 w-5" />
          Comments ({page.comments_count || 0})
          <ChevronDown className={`h-4 w-4 transition-transform ${showComments ? 'rotate-180' : ''}`} />
        </button>
        {showComments && <PageComments pageId={page.id} />}
      </div>
      )}

      {/* Related pages */}
      {!zen && (
      <div className="mt-8">
        <button
          onClick={() => setShowRelated(!showRelated)}
          className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white mb-4 hover:text-shizuha-600"
        >
          <Network className="h-5 w-5" />
          Related pages
          <ChevronDown className={`h-4 w-4 transition-transform ${showRelated ? 'rotate-180' : ''}`} />
        </button>
        {showRelated && <RelatedPages pageId={page.id} spaceKey={spaceKey} />}
      </div>
      )}

      {/* Backlinks */}
      {!zen && (
      <div className="mt-8">
        <button
          onClick={() => setShowBacklinks(!showBacklinks)}
          className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white mb-4 hover:text-shizuha-600"
        >
          <Link2 className="h-5 w-5" />
          Linked from
          <ChevronDown className={`h-4 w-4 transition-transform ${showBacklinks ? 'rotate-180' : ''}`} />
        </button>
        {showBacklinks && <PageBacklinks pageId={page.id} spaceKey={spaceKey} />}
      </div>
      )}
    </div>
  )
}

function ChildPages({ pageId, spaceKey }) {
  const { data: children = [], isLoading } = useQuery({
    queryKey: ['page', pageId, 'children'],
    queryFn: async () => {
      const response = await pagesApi.getChildren(pageId)
      return response.data
    },
  })

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="grid md:grid-cols-2 gap-4">
      {children.map((child) => (
        <Link
          key={child.id}
          to={`/spaces/${spaceKey}/pages/${child.slug}`}
          className="block p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600"
        >
          <h3 className="font-medium text-gray-900 dark:text-white">{child.title}</h3>
        </Link>
      ))}
    </div>
  )
}


function RelatedPages({ pageId, spaceKey }) {
  const { data: related = [], isLoading } = useQuery({
    queryKey: ['page', pageId, 'related'],
    queryFn: async () => {
      const response = await pagesApi.getRelated(pageId, { limit: 6 })
      return response.data
    },
  })

  if (isLoading) return <LoadingSpinner />

  if (related.length === 0) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">No related pages found yet.</p>
  }

  const reasonLabel = (reason) => ({
    shared_labels: 'shared labels',
    linked: 'linked',
    nearby_link: 'nearby link',
    similar_content: 'similar content',
  }[reason] || reason)

  return (
    <div className="grid md:grid-cols-2 gap-4">
      {related.map((p) => (
        <Link
          key={p.id}
          to={`/spaces/${p.space_key || spaceKey}/pages/${p.slug}`}
          className="block p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600"
        >
          <div className="flex items-start justify-between gap-3">
            <h3 className="font-medium text-gray-900 dark:text-white">{p.title}</h3>
            {p.related_score && (
              <span className="text-xs text-gray-500 dark:text-gray-400">{Number(p.related_score).toFixed(1)}</span>
            )}
          </div>
          {p.related_reasons?.length > 0 && (
            <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
              {p.related_reasons.map(reasonLabel).join(' · ')}
            </p>
          )}
          {p.space_key && p.space_key !== spaceKey && (
            <span className="text-xs text-gray-500 dark:text-gray-400">{p.space_key}</span>
          )}
        </Link>
      ))}
    </div>
  )
}

function PageBacklinks({ pageId, spaceKey }) {
  const { data: backlinks = [], isLoading } = useQuery({
    queryKey: ['page', pageId, 'backlinks'],
    queryFn: async () => {
      const response = await pagesApi.getBacklinks(pageId)
      return response.data
    },
  })

  if (isLoading) return <LoadingSpinner />

  if (backlinks.length === 0) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">No pages link here yet.</p>
  }

  return (
    <div className="grid md:grid-cols-2 gap-4">
      {backlinks.map((p) => (
        <Link
          key={p.id}
          to={`/spaces/${p.space_key || spaceKey}/pages/${p.slug}`}
          className="block p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600"
        >
          <h3 className="font-medium text-gray-900 dark:text-white">{p.title}</h3>
          {p.space_key && p.space_key !== spaceKey && (
            <span className="text-xs text-gray-500 dark:text-gray-400">{p.space_key}</span>
          )}
        </Link>
      ))}
    </div>
  )
}

function PageVersions({ pageId }) {
  const queryClient = useQueryClient()
  const [restoring, setRestoring] = useState(null)

  const { data: versions = [], isLoading } = useQuery({
    queryKey: ['page', pageId, 'versions'],
    queryFn: async () => {
      const response = await pagesApi.getVersions(pageId)
      return response.data
    },
  })

  const handleRestore = async (versionNumber) => {
    if (!confirm(`Are you sure you want to restore to version ${versionNumber}? This will create a new version with the restored content.`)) {
      return
    }

    setRestoring(versionNumber)
    try {
      await pagesApi.restoreVersion(pageId, versionNumber)
      // Invalidate queries to refresh page and versions
      queryClient.invalidateQueries({ queryKey: ['page'] })
      queryClient.invalidateQueries({ queryKey: ['pages'] })
    } catch (error) {
      console.error('Failed to restore version:', error)
      alert('Failed to restore version. Please try again.')
    } finally {
      setRestoring(null)
    }
  }

  if (isLoading) return <LoadingSpinner />

  if (versions.length === 0) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400">No version history available.</p>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-200 dark:divide-gray-700">
      {versions.map((version, index) => (
        <div key={version.id} className="p-4 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-900 dark:text-white">
                Version {version.version_number}
              </span>
              {index === 0 && (
                <span className="text-xs px-2 py-0.5 bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 rounded">
                  Current
                </span>
              )}
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {version.change_message || 'No description'}
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500">
              {format(new Date(version.created_at), 'MMM d, yyyy h:mm a')}
            </p>
          </div>
          {index > 0 && (
            <button
              onClick={() => handleRestore(version.version_number)}
              disabled={restoring === version.version_number}
              className="text-sm text-shizuha-600 hover:underline disabled:opacity-50"
            >
              {restoring === version.version_number ? 'Restoring...' : 'Restore'}
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

function PageComments({ pageId }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [newComment, setNewComment] = useState('')
  const [replyingTo, setReplyingTo] = useState(null)
  const [replyContent, setReplyContent] = useState('')

  const { data: comments = [], isLoading } = useQuery({
    queryKey: ['page', pageId, 'comments'],
    queryFn: async () => {
      const response = await commentsApi.list(pageId)
      return response.data.results || response.data
    },
  })

  const addCommentMutation = useMutation({
    mutationFn: ({ content, parent }) => commentsApi.create({ page: pageId, content, parent }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['page', pageId, 'comments'] })
      queryClient.invalidateQueries({ queryKey: ['page'] })
      setNewComment('')
      setReplyingTo(null)
      setReplyContent('')
    },
  })

  const resolveCommentMutation = useMutation({
    mutationFn: (commentId) => commentsApi.resolve(commentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['page', pageId, 'comments'] })
    },
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    if (newComment.trim()) {
      addCommentMutation.mutate({ content: newComment.trim(), parent: null })
    }
  }

  const handleReply = (commentId) => {
    if (replyContent.trim()) {
      addCommentMutation.mutate({ content: replyContent.trim(), parent: commentId })
    }
  }

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="space-y-4">
      {/* Add comment form */}
      <form onSubmit={handleSubmit} className="flex gap-3">
        <div className="h-10 w-10 rounded-full bg-shizuha-600 flex items-center justify-center text-white font-medium flex-shrink-0">
          {user?.username?.[0]?.toUpperCase() || 'U'}
        </div>
        <div className="flex-1">
          <textarea
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
            placeholder="Add a comment..."
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 resize-none"
            rows={2}
          />
          <div className="flex justify-end mt-2">
            <button
              type="submit"
              disabled={!newComment.trim() || addCommentMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 disabled:opacity-50"
            >
              <Send className="h-4 w-4" />
              Comment
            </button>
          </div>
        </div>
      </form>

      {/* Comments list */}
      {comments.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
          No comments yet. Be the first to comment!
        </p>
      ) : (
        <div className="space-y-4">
          {comments.map((comment) => (
            <CommentItem
              key={comment.id}
              comment={comment}
              user={user}
              replyingTo={replyingTo}
              setReplyingTo={setReplyingTo}
              replyContent={replyContent}
              setReplyContent={setReplyContent}
              onReply={handleReply}
              onResolve={() => resolveCommentMutation.mutate(comment.id)}
              isSubmitting={addCommentMutation.isPending}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function CommentItem({ comment, user, replyingTo, setReplyingTo, replyContent, setReplyContent, onReply, onResolve, isSubmitting }) {
  const isReplying = replyingTo === comment.id

  // Generate a consistent color based on user ID
  const getAvatarColor = (userId) => {
    const colors = [
      'bg-blue-500', 'bg-green-500', 'bg-purple-500', 'bg-pink-500',
      'bg-indigo-500', 'bg-teal-500', 'bg-orange-500', 'bg-cyan-500'
    ]
    return colors[(userId || 0) % colors.length]
  }

  return (
    <div className="flex gap-3">
      <div className={`h-10 w-10 rounded-full ${getAvatarColor(comment.created_by_id)} flex items-center justify-center text-white font-medium flex-shrink-0`}>
        {String(comment.created_by_id).charAt(0).toUpperCase()}
      </div>
      <div className="flex-1">
        <div className={`bg-white dark:bg-gray-800 rounded-lg border ${comment.is_resolved ? 'border-green-200 dark:border-green-800' : 'border-gray-200 dark:border-gray-700'} p-4`}>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-900 dark:text-white">
                {comment.author_name || comment.author_email || `User #${comment.created_by_id}`}
              </span>
              {comment.is_resolved && (
                <span className="text-xs px-2 py-0.5 bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 rounded">
                  Resolved
                </span>
              )}
            </div>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {formatDistanceToNow(new Date(comment.created_at), { addSuffix: true })}
            </span>
          </div>
          <p className="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{comment.content}</p>

          {/* Action buttons */}
          <div className="flex items-center gap-4 mt-3 pt-3 border-t border-gray-100 dark:border-gray-700">
            <button
              onClick={() => setReplyingTo(isReplying ? null : comment.id)}
              className="text-sm text-gray-500 hover:text-shizuha-600 dark:text-gray-400 dark:hover:text-shizuha-400"
            >
              Reply
            </button>
            {!comment.is_resolved && (
              <button
                onClick={onResolve}
                className="text-sm text-gray-500 hover:text-green-600 dark:text-gray-400 dark:hover:text-green-400"
              >
                Resolve
              </button>
            )}
          </div>
        </div>

        {/* Reply form */}
        {isReplying && (
          <div className="mt-2 ml-4 flex gap-2">
            <div className={`h-8 w-8 rounded-full bg-shizuha-600 flex items-center justify-center text-white text-sm font-medium flex-shrink-0`}>
              {user?.username?.[0]?.toUpperCase() || 'U'}
            </div>
            <div className="flex-1">
              <textarea
                value={replyContent}
                onChange={(e) => setReplyContent(e.target.value)}
                placeholder="Write a reply..."
                className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 resize-none"
                rows={2}
                autoFocus
              />
              <div className="flex justify-end gap-2 mt-2">
                <button
                  onClick={() => {
                    setReplyingTo(null)
                    setReplyContent('')
                  }}
                  className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={() => onReply(comment.id)}
                  disabled={!replyContent.trim() || isSubmitting}
                  className="px-3 py-1.5 text-sm bg-shizuha-600 text-white rounded hover:bg-shizuha-700 disabled:opacity-50"
                >
                  Reply
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Existing replies */}
        {comment.replies && comment.replies.length > 0 && (
          <div className="mt-3 ml-4 space-y-3">
            {comment.replies.map((reply) => (
              <div key={reply.id} className="flex gap-2">
                <div className={`h-8 w-8 rounded-full ${getAvatarColor(reply.created_by_id)} flex items-center justify-center text-white text-sm font-medium flex-shrink-0`}>
                  {String(reply.created_by_id).charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-gray-900 dark:text-white">
                      {reply.author_name || reply.author_email || `User #${reply.created_by_id}`}
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {formatDistanceToNow(new Date(reply.created_at), { addSuffix: true })}
                    </span>
                  </div>
                  <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{reply.content}</p>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Show more replies indicator */}
        {comment.replies_count > (comment.replies?.length || 0) && (
          <p className="mt-2 ml-4 text-sm text-shizuha-600 dark:text-shizuha-400">
            + {comment.replies_count - (comment.replies?.length || 0)} more replies
          </p>
        )}
      </div>
    </div>
  )
}

// Icon SVG strings for callout rendering
const CALLOUT_ICONS = {
  info: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
  note: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/></svg>',
  tip: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/></svg>',
  warning: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
  error: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></svg>',
}

const TOC_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" x2="21" y1="6" y2="6"/><line x1="8" x2="21" y1="12" y2="12"/><line x1="8" x2="21" y1="18" y2="18"/><line x1="3" x2="3.01" y1="6" y2="6"/><line x1="3" x2="3.01" y1="12" y2="12"/><line x1="3" x2="3.01" y1="18" y2="18"/></svg>'

function renderContent(contentJson) {
  if (!contentJson || !contentJson.content) {
    return '<p class="text-gray-500">No content yet.</p>'
  }

  // Extract headings for TOC
  const headings = []
  const extractHeadings = (node, index = 0) => {
    if (!node) return
    if (node.type === 'heading') {
      const level = node.attrs?.level || 1
      const text = node.content?.map(n => n.text || '').join('') || ''
      const id = `heading-${headings.length}`
      headings.push({ level, text, id })
    }
    if (node.content) {
      node.content.forEach((child, i) => extractHeadings(child, i))
    }
  }
  extractHeadings(contentJson)

  let headingIndex = 0

  // Basic TipTap JSON to HTML conversion
  const renderNode = (node) => {
    if (!node) return ''

    switch (node.type) {
      case 'doc':
        return node.content?.map(renderNode).join('') || ''
      case 'paragraph':
        const pContent = node.content?.map(renderNode).join('') || ''
        return `<p>${pContent}</p>`
      case 'heading':
        const hContent = node.content?.map(renderNode).join('') || ''
        const headingId = `heading-${headingIndex++}`
        return `<h${node.attrs?.level || 1} id="${headingId}">${hContent}</h${node.attrs?.level || 1}>`
      case 'bulletList':
        return `<ul>${node.content?.map(renderNode).join('')}</ul>`
      case 'orderedList':
        return `<ol>${node.content?.map(renderNode).join('')}</ol>`
      case 'listItem':
        return `<li>${node.content?.map(renderNode).join('')}</li>`
      case 'codeBlock':
        if (/^atlas$/i.test(node.attrs?.language || node.attrs?.lang || '')) {
          return renderAtlasPlaceholder((node.content || []).map(child => child.text || '').join(''))
        }
        const code = node.content?.map(renderNode).join('') || ''
        const lang = String(node.attrs?.language || node.attrs?.lang || '').toLowerCase()
        if (lang === 'mermaid') {
          return `<div class="${WIKI_MERMAID_CLASS}">${code}</div>`
        }
        return `<pre><code>${code}</code></pre>`
      case 'blockquote':
        return `<blockquote>${node.content?.map(renderNode).join('')}</blockquote>`
      case 'horizontalRule':
        return '<hr />'
      case 'image':
        return renderSafeImageTag(node.attrs || {})
      case 'callout':
        const calloutType = node.attrs?.type || 'info'
        const calloutContent = node.content?.map(renderNode).join('') || ''
        const icon = CALLOUT_ICONS[calloutType] || CALLOUT_ICONS.info
        return `
          <div class="callout-rendered callout-${calloutType} flex gap-3">
            <div class="callout-icon">${icon}</div>
            <div class="callout-body">${calloutContent}</div>
          </div>
        `
      case 'tableOfContents':
        if (headings.length === 0) {
          return `
            <div class="toc-rendered">
              <div class="toc-header">
                <span class="text-gray-500 dark:text-gray-400">${TOC_ICON}</span>
                <span class="toc-title">Table of Contents</span>
              </div>
              <p class="text-sm text-gray-500 dark:text-gray-400 italic">No headings found.</p>
            </div>
          `
        }
        const tocItems = headings.map(h => {
          const indent = (h.level - 1) * 16
          return `<li style="padding-left: ${indent}px;" class="toc-level-${h.level}"><a href="#${h.id}">${h.text || 'Untitled'}</a></li>`
        }).join('')
        return `
          <div class="toc-rendered">
            <div class="toc-header">
              <span class="text-gray-500 dark:text-gray-400">${TOC_ICON}</span>
              <span class="toc-title">Table of Contents</span>
            </div>
            <ul class="toc-list">${tocItems}</ul>
          </div>
        `
      case 'table':
        return `<table>${node.content?.map(renderNode).join('')}</table>`
      case 'tableRow':
        return `<tr>${node.content?.map(renderNode).join('')}</tr>`
      case 'tableHeader':
        return `<th>${node.content?.map(renderNode).join('')}</th>`
      case 'tableCell':
        return `<td>${node.content?.map(renderNode).join('')}</td>`
      case 'text':
        let text = node.text || ''
        if (node.marks) {
          node.marks.forEach((mark) => {
            switch (mark.type) {
              case 'bold':
                text = `<strong>${text}</strong>`
                break
              case 'italic':
                text = `<em>${text}</em>`
                break
              case 'code':
                text = `<code>${text}</code>`
                break
              case 'link':
                text = `<a href="${mark.attrs?.href}" target="_blank">${text}</a>`
                break
              case 'highlight':
                text = `<mark>${text}</mark>`
                break
            }
          })
        }
        return text
      default:
        return node.content?.map(renderNode).join('') || ''
    }
  }

  return sanitizePageContent(renderNode(contentJson))
}

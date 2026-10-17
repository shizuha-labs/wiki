import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useEditor, EditorContent } from '@tiptap/react'
import { useDropzone } from 'react-dropzone'
import {
  createWikiExtensions,
  useEditorSync,
  Toolbar,
} from '@shizuha/editor'
import {
  Save, ArrowLeft, Tag, X, Plus, Upload,
} from 'lucide-react'
import { spacesApi, pagesApi, labelsApi, attachmentsApi } from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'
import { useSpace } from '../contexts/SpaceContext'
import { AttachmentPanel, MAX_FILE_SIZE, validateFile } from '../components/attachments'
import { useToast } from '../components/Toast'
import { docToMarkdown } from '../utils/pageContent'

// Create extensions once at module level to avoid recreating on each render
const wikiExtensions = createWikiExtensions({ placeholder: 'Start writing your page content...' })

export default function PageEditor() {
  const { spaceKey, pageSlug } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { spaces } = useSpace()
  const toast = useToast()
  const isEditing = !!pageSlug

  const [title, setTitle] = useState('')
  const [selectedSpace, setSelectedSpace] = useState(spaceKey || '')
  const [parentId, setParentId] = useState(null)
  const [status, setStatus] = useState('published')
  const [saving, setSaving] = useState(false)
  const [autoSaved, setAutoSaved] = useState(false)
  const [selectedLabels, setSelectedLabels] = useState([])
  const [showLabelSelector, setShowLabelSelector] = useState(false)
  const [newLabelName, setNewLabelName] = useState('')
  const [showAttachmentPanel, setShowAttachmentPanel] = useState(false)
  const [isDraggingFile, setIsDraggingFile] = useState(false)
  const [uploadProgress, setUploadProgress] = useState({})
  const [autoSavedPage, setAutoSavedPage] = useState(null)
  const attachmentPanelRef = useRef(null)
  const autoSaveDataRef = useRef({})

  // Get space details
  const space = spaces.find(s => s.key === selectedSpace)

  // Fetch available labels
  const { data: availableLabels = [] } = useQuery({
    queryKey: ['labels'],
    queryFn: async () => {
      const response = await labelsApi.list()
      return response.data.results || response.data
    },
  })

  // Create label mutation
  const createLabelMutation = useMutation({
    mutationFn: (name) => labelsApi.create({ name, color: getRandomColor() }),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['labels'] })
      const newLabel = response.data
      setSelectedLabels(prev => [...prev, newLabel])
      setNewLabelName('')
      toast.success(`Label "${response.data.name}" created`)
    },
    onError: (error) => {
      const msg = error.response?.data?.name?.[0]
        || error.response?.data?.detail
        || error.message
        || 'Failed to create label'
      toast.error(msg)
    },
  })

  // Fetch pages in the selected space for parent selection
  const { data: spacePages = [] } = useQuery({
    queryKey: ['pages', selectedSpace, 'list'],
    queryFn: async () => {
      const response = await pagesApi.list({ space_key: selectedSpace })
      return response.data.results || response.data
    },
    enabled: !!selectedSpace,
  })

  // Fetch existing page if editing
  const { data: existingPage, isLoading: pageLoading } = useQuery({
    queryKey: ['page', spaceKey, pageSlug],
    queryFn: async () => {
      const response = await pagesApi.list({ space_key: spaceKey, slug: pageSlug })
      const pages = response.data.results || response.data
      if (pages.length > 0) {
        const detailResponse = await pagesApi.get(pages[0].id)
        return detailResponse.data
      }
      return null
    },
    enabled: isEditing,
  })

  // Effective page: existingPage (from query) or autoSavedPage (from auto-save for attachments)
  const effectivePage = existingPage || autoSavedPage
  const pageId = effectivePage?.id

  // TipTap editor - use module-level extensions to avoid duplicate plugin instances
  const editor = useEditor({
    extensions: wikiExtensions,
    content: '',
    editorProps: {
      attributes: {
        class: 'prose dark:prose-invert max-w-none focus:outline-none min-h-[400px]',
      },
    },
  })


  // Load existing page data (metadata only)
  useEffect(() => {
    if (existingPage) {
      setTitle(existingPage.title)
      setStatus(existingPage.status)
      setParentId(existingPage.parent)
      if (existingPage.labels) {
        setSelectedLabels(existingPage.labels)
      }
    }
  }, [existingPage])

  // Sync content to editor using shared hook
  useEditorSync(editor, existingPage?.content_json)

  // Create/Update mutation
  // Note: onSuccess handles cache updates; navigation is controlled by the caller
  const saveMutation = useMutation({
    mutationFn: async (data) => {
      if ((isEditing && existingPage) || autoSavedPage) {
        return pagesApi.update((existingPage || autoSavedPage).id, data)
      } else {
        return pagesApi.create(data)
      }
    },
    onSuccess: (response) => {
      const page = response.data

      // Optimistic cache update for immediate UI feedback
      if (isEditing && existingPage) {
        // Update the single page cache
        queryClient.setQueryData(['page', spaceKey, pageSlug], page)

        // Update pages lists
        queryClient.setQueriesData(
          { queryKey: ['pages'], exact: false },
          (oldData) => {
            if (!oldData) return oldData
            const results = oldData.results || oldData
            if (!Array.isArray(results)) return oldData
            const updatedResults = results.map(p =>
              p.id === existingPage.id
                ? { ...p, title: page.title, updated_at: page.updated_at, status: page.status }
                : p
            )
            return oldData.results ? { ...oldData, results: updatedResults } : updatedResults
          }
        )

        // Update space tree (page titles in sidebar)
        queryClient.setQueriesData(
          { queryKey: ['space', spaceKey, 'tree'], exact: false },
          (oldData) => {
            if (!oldData) return oldData
            // Recursively update page in tree
            const updatePageInTree = (pages) => {
              return pages.map(p => {
                if (p.id === existingPage.id) {
                  return { ...p, title: page.title, status: page.status }
                }
                if (p.children && p.children.length > 0) {
                  return { ...p, children: updatePageInTree(p.children) }
                }
                return p
              })
            }
            return updatePageInTree(oldData)
          }
        )
      }

      // Background refetch for consistency
      queryClient.invalidateQueries({ queryKey: ['pages'] })
      queryClient.invalidateQueries({ queryKey: ['space', spaceKey, 'tree'] })

      // Note: Navigation is NOT done here - it's handled by the caller
      // This allows auto-save to work without navigating away from the editor
    },
  })

  // Upload attachment mutation - accepts targetPageId to avoid stale closure
  const uploadAttachmentMutation = useMutation({
    mutationFn: ({ file, targetPageId }) =>
      attachmentsApi.upload(targetPageId, file, (progress) => {
        setUploadProgress((prev) => ({ ...prev, [file.name]: progress }))
      }),
    onSuccess: (_, { file, targetPageId }) => {
      queryClient.invalidateQueries({ queryKey: ['attachments', targetPageId] })
      queryClient.invalidateQueries({ queryKey: ['page'] })
      toast.success(`Uploaded ${file.name}`)
    },
    onError: (error, { file }) => {
      setUploadProgress((prev) => ({ ...prev, [file.name]: -1 }))
      toast.error(error.response?.data?.detail || `Failed to upload ${file.name}`)
    },
    onSettled: (_, __, { file }) => {
      setTimeout(() => {
        setUploadProgress((prev) => {
          const { [file.name]: _, ...rest } = prev
          return rest
        })
      }, 1000)
    },
  })

  // State to hold pending files while page is being auto-saved
  const [pendingFiles, setPendingFiles] = useState([])

  // Auto-save page to enable attachments
  const autoSaveForAttachments = useCallback(async () => {
    if (!title.trim()) {
      toast.warning('Please enter a page title first')
      return null
    }
    if (!space) {
      toast.warning('Please select a space first')
      return null
    }

    setSaving(true)
    try {
      const contentJson = editor?.getJSON() || { type: 'doc', content: [] }
      // WIKI-120: serialize the doc to Markdown (getText() flattens headings/fences).
      const contentText = docToMarkdown(contentJson)

      const response = await pagesApi.create({
        space: space.id,
        title: title.trim(),
        content_json: contentJson,
        content_text: contentText,
        status: 'draft', // Save as draft initially
        parent: parentId,
        label_ids: selectedLabels.map(l => l.id),
      })

      queryClient.invalidateQueries({ queryKey: ['pages'] })
      queryClient.invalidateQueries({ queryKey: ['space', spaceKey, 'tree'] })

      // Store auto-saved page so the rest of the component can use its ID
      const newPage = response.data
      setAutoSavedPage(newPage)

      // Update URL to reflect the new page without full navigation
      window.history.replaceState(null, '', `/wiki/spaces/${newPage.space_key || spaceKey}/pages/${newPage.slug}/edit`)

      toast.success('Page saved as draft')
      return newPage
    } catch (error) {
      toast.error('Failed to save page')
      return null
    } finally {
      setSaving(false)
    }
  }, [title, space, editor, parentId, selectedLabels, spaceKey, queryClient, toast])

  // Handle file drop on editor
  const handleFileDrop = useCallback(async (acceptedFiles) => {
    let targetPageId = pageId

    // If page doesn't exist yet, auto-save it first
    if (!targetPageId) {
      const newPage = await autoSaveForAttachments()
      if (!newPage) {
        return // Failed to save, message already shown
      }
      targetPageId = newPage.id
    }

    acceptedFiles.forEach((file) => {
      const errors = validateFile(file)
      if (errors.length === 0) {
        uploadAttachmentMutation.mutate({ file, targetPageId })
        setShowAttachmentPanel(true)
      } else {
        toast.error(`${file.name}: ${errors.join(', ')}`)
      }
    })
  }, [pageId, uploadAttachmentMutation, toast, autoSaveForAttachments])

  // Process pending files after page is saved (via auto-save or query)
  useEffect(() => {
    if (pageId && pendingFiles.length > 0) {
      pendingFiles.forEach((file) => {
        const errors = validateFile(file)
        if (errors.length === 0) {
          uploadAttachmentMutation.mutate({ file, targetPageId: pageId })
          setShowAttachmentPanel(true)
        } else {
          toast.error(`${file.name}: ${errors.join(', ')}`)
        }
      })
      setPendingFiles([])
    }
  }, [pageId, pendingFiles, uploadAttachmentMutation, toast])

  // Insert attachment into editor content
  const handleInsertAttachment = useCallback((attachment) => {
    if (!editor) return

    const isImage = attachment.mime_type?.startsWith('image/')
    if (isImage) {
      editor.chain().focus().setImage({
        src: attachmentsApi.getViewUrl(attachment.id),
        alt: attachment.filename,
      }).run()
    } else {
      // Insert as link
      editor.chain().focus().insertContent({
        type: 'text',
        text: attachment.filename,
        marks: [{ type: 'link', attrs: { href: attachmentsApi.getDownloadUrl(attachment.id) } }],
      }).run()
    }
    toast.success(`Inserted ${attachment.filename}`)
  }, [editor, toast])

  // Dropzone for the editor area
  const { getRootProps: getEditorDropProps, getInputProps: getEditorDropInput, isDragActive } = useDropzone({
    onDrop: handleFileDrop,
    noClick: true,
    noKeyboard: true,
    maxSize: MAX_FILE_SIZE,
    onDragEnter: () => setIsDraggingFile(true),
    onDragLeave: () => setIsDraggingFile(false),
    onDropAccepted: () => setIsDraggingFile(false),
    onDropRejected: () => setIsDraggingFile(false),
  })

  // Refs to track last-saved content for auto-save change detection
  const lastSavedContentRef = useRef(null)
  const lastSavedTitleRef = useRef(null)

  // Save handler
  // navigateAfterSave: true for manual save button, false for auto-save
  const handleSave = useCallback(async (navigateAfterSave = true) => {
    if (!title.trim() || !editor || !space) return

    setSaving(true)
    const contentJson = editor.getJSON()
    // WIKI-120: serialize the doc to Markdown (getText() flattens headings/fences).
    const contentText = docToMarkdown(contentJson)

    const response = await saveMutation.mutateAsync({
      space: space.id,
      title: title.trim(),
      content_json: contentJson,
      content_text: contentText,
      status,
      parent: parentId,
      label_ids: selectedLabels.map(l => l.id),
    })
    setSaving(false)

    // Update auto-save refs so it doesn't re-save the same content
    lastSavedContentRef.current = JSON.stringify(contentJson)
    lastSavedTitleRef.current = title

    // If this was a new page that just got created, track it
    if (!isEditing && !autoSavedPage && response?.data) {
      setAutoSavedPage(response.data)
    }

    // Only navigate if explicitly requested (manual save)
    if (navigateAfterSave && response?.data) {
      const page = response.data
      navigate(`/spaces/${page.space_key || spaceKey}/pages/${page.slug}`)
    }
  }, [title, editor, space, status, parentId, selectedLabels, saveMutation, navigate, spaceKey, isEditing, autoSavedPage])

  // Initialize refs when page loads (from query or auto-save)
  useEffect(() => {
    if (effectivePage) {
      lastSavedContentRef.current = JSON.stringify(effectivePage.content_json)
      lastSavedTitleRef.current = effectivePage.title
    }
  }, [effectivePage?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Keep ref in sync with current state so interval callback reads fresh values
  useEffect(() => {
    autoSaveDataRef.current = { title, space, status, parentId, selectedLabels }
  })

  // Auto-save with stable interval (does NOT navigate away from editor)
  useEffect(() => {
    if (!(isEditing || autoSavedPage) || !effectivePage || !editor) return

    const interval = setInterval(() => {
      if (editor.isDestroyed) return

      const { title: currentTitle, space: currentSpace, status: currentStatus, parentId: currentParentId, selectedLabels: currentLabels } = autoSaveDataRef.current
      const currentContent = JSON.stringify(editor.getJSON())

      const contentChanged = currentContent !== lastSavedContentRef.current
      const titleChanged = currentTitle !== lastSavedTitleRef.current

      if ((contentChanged || titleChanged) && currentTitle.trim()) {
        const contentJson = editor.getJSON()
        // WIKI-120: serialize the doc to Markdown (getText() flattens headings/fences).
        const contentText = docToMarkdown(contentJson)

        saveMutation.mutateAsync({
          space: currentSpace?.id,
          title: currentTitle.trim(),
          content_json: contentJson,
          content_text: contentText,
          status: currentStatus,
          parent: currentParentId,
          label_ids: currentLabels.map(l => l.id),
        }).then(() => {
          lastSavedContentRef.current = currentContent
          lastSavedTitleRef.current = currentTitle
          setAutoSaved(true)
          setTimeout(() => setAutoSaved(false), 2000)
        }).catch(() => {
          // Silently fail auto-save, user can manually save
        })
      }
    }, 5000)

    return () => clearInterval(interval)
  }, [isEditing, !!effectivePage, !!autoSavedPage, !!editor]) // eslint-disable-line react-hooks/exhaustive-deps

  if (pageLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
        >
          <ArrowLeft className="h-5 w-5" />
          Back
        </button>
        <div className="flex items-center gap-3">
          {autoSaved && (
            <span className="text-sm text-green-600 dark:text-green-400">Saved</span>
          )}
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm"
          >
            <option value="draft">Draft</option>
            <option value="published">Published</option>
          </select>
          <button
            onClick={handleSave}
            disabled={saving || !title.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      {/* Space and parent page selectors */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        {/* Space selector for new pages */}
        {!isEditing && (
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Space
            </label>
            <select
              value={selectedSpace}
              onChange={(e) => {
                setSelectedSpace(e.target.value)
                setParentId(null) // Reset parent when space changes
              }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
            >
              <option value="">Select a space</option>
              {spaces.map((s) => (
                <option key={s.id} value={s.key}>{s.name}</option>
              ))}
            </select>
          </div>
        )}

        {/* Parent page selector */}
        {selectedSpace && (
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Parent Page (optional)
            </label>
            <select
              value={parentId || ''}
              onChange={(e) => setParentId(e.target.value || null)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
            >
              <option value="">No parent (root level)</option>
              {spacePages
                .filter(p => !existingPage || p.id !== existingPage.id) // Don't allow page to be its own parent
                .map((p) => (
                  <option key={p.id} value={p.id}>{p.title}</option>
                ))}
            </select>
          </div>
        )}
      </div>

      {/* Labels section */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Labels
        </label>
        <div className="flex flex-wrap items-center gap-2">
          {/* Selected labels */}
          {selectedLabels.map((label) => (
            <span
              key={label.id}
              className="inline-flex items-center gap-1 px-2 py-1 text-sm rounded-full"
              style={{ backgroundColor: label.color + '20', color: label.color }}
            >
              <Tag className="h-3 w-3" />
              {label.name}
              <button
                onClick={() => setSelectedLabels(prev => prev.filter(l => l.id !== label.id))}
                className="hover:opacity-70"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}

          {/* Add label button */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowLabelSelector(!showLabelSelector)}
              className="inline-flex items-center gap-1 px-2 py-1 text-sm text-gray-500 dark:text-gray-400 border border-dashed border-gray-300 dark:border-gray-600 rounded-full hover:border-gray-400 dark:hover:border-gray-500"
            >
              <Plus className="h-3 w-3" />
              Add label
            </button>

            {/* Label selector dropdown */}
            {showLabelSelector && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setShowLabelSelector(false)}
                />
                <div className="absolute left-0 top-full mt-1 z-50 w-64 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-2">
                  {/* Existing labels */}
                  <div className="max-h-48 overflow-y-auto">
                    {availableLabels
                      .filter(l => !selectedLabels.find(sl => sl.id === l.id))
                      .map((label) => (
                        <button
                          key={label.id}
                          onClick={() => {
                            setSelectedLabels(prev => [...prev, label])
                            setShowLabelSelector(false)
                          }}
                          className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700"
                        >
                          <span
                            className="w-3 h-3 rounded-full"
                            style={{ backgroundColor: label.color }}
                          />
                          <span className="text-sm text-gray-900 dark:text-white">{label.name}</span>
                        </button>
                      ))}
                    {availableLabels.filter(l => !selectedLabels.find(sl => sl.id === l.id)).length === 0 && (
                      <p className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">
                        No more labels available
                      </p>
                    )}
                  </div>

                  {/* Create new label */}
                  <div className="border-t border-gray-200 dark:border-gray-700 px-3 py-2 mt-2">
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Create new label</p>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={newLabelName}
                        onChange={(e) => setNewLabelName(e.target.value)}
                        placeholder="Label name"
                        className="flex-1 px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && newLabelName.trim()) {
                            createLabelMutation.mutate(newLabelName.trim())
                          }
                        }}
                      />
                      <button
                        onClick={() => {
                          if (newLabelName.trim()) {
                            createLabelMutation.mutate(newLabelName.trim())
                          }
                        }}
                        disabled={!newLabelName.trim() || createLabelMutation.isPending}
                        className="px-2 py-1 text-sm bg-shizuha-600 text-white rounded hover:bg-shizuha-700 disabled:opacity-50"
                      >
                        Add
                      </button>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Title input */}
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Page title"
        className="w-full text-3xl font-bold border-0 border-b border-gray-200 dark:border-gray-700 bg-transparent text-gray-900 dark:text-white placeholder-gray-400 focus:ring-0 focus:border-shizuha-500 pb-4 mb-6"
      />

      {/* Toolbar - using shared component */}
      {editor && (
        <Toolbar
          editor={editor}
          preset="wiki"
          sticky
          onAttachmentClick={() => setShowAttachmentPanel(!showAttachmentPanel)}
          showAttachments={true}
          className="mb-4"
        />
      )}

      {/* Editor with dropzone wrapper */}
      <div {...getEditorDropProps()} className="relative">
        <input {...getEditorDropInput()} />

        {/* Drop overlay */}
        {isDragActive && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-shizuha-50/90 dark:bg-shizuha-900/90 border-2 border-dashed border-shizuha-500 rounded-lg">
            <div className="flex flex-col items-center gap-2 text-shizuha-600 dark:text-shizuha-400">
              <Upload className="h-12 w-12" />
              <p className="text-lg font-medium">Drop files to attach</p>
            </div>
          </div>
        )}

        {/* Editor */}
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
          <EditorContent editor={editor} />
        </div>
      </div>

      {/* Attachments Panel */}
      {showAttachmentPanel && (
        <div className="mt-4" ref={attachmentPanelRef}>
          <AttachmentPanel
            pageId={pageId}
            onInsert={handleInsertAttachment}
            onAutoSave={!pageId ? autoSaveForAttachments : null}
            defaultExpanded={true}
          />
        </div>
      )}
    </div>
  )
}

// Generate a random color for new labels
function getRandomColor() {
  const colors = [
    '#ef4444', // red
    '#f97316', // orange
    '#eab308', // yellow
    '#22c55e', // green
    '#14b8a6', // teal
    '#3b82f6', // blue
    '#8b5cf6', // violet
    '#ec4899', // pink
    '#6366f1', // indigo
    '#06b6d4', // cyan
  ]
  return colors[Math.floor(Math.random() * colors.length)]
}

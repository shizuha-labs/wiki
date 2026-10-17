import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Paperclip, ChevronDown, AlertCircle } from 'lucide-react'
import { attachmentsApi } from '../../services/api'
import AttachmentUploadZone from './AttachmentUploadZone'
import AttachmentItem from './AttachmentItem'
import LoadingSpinner from '../LoadingSpinner'
import { useToast } from '../Toast'

export default function AttachmentPanel({
  pageId,
  onInsert,
  onAutoSave,
  readOnly = false,
  defaultExpanded = false,
}) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)
  const [uploadProgress, setUploadProgress] = useState({})
  const queryClient = useQueryClient()
  const toast = useToast()

  // Fetch attachments for this page
  const { data: attachments = [], isLoading } = useQuery({
    queryKey: ['attachments', pageId],
    queryFn: async () => {
      const response = await attachmentsApi.list(pageId)
      return response.data.results || response.data || []
    },
    enabled: !!pageId,
  })

  // Upload mutation - accepts targetPageId to avoid stale closure over pageId prop
  const uploadMutation = useMutation({
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
      // Clean up progress after a short delay
      setTimeout(() => {
        setUploadProgress((prev) => {
          const { [file.name]: _, ...rest } = prev
          return rest
        })
      }, 1000)
    },
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (id) => attachmentsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attachments', pageId] })
      queryClient.invalidateQueries({ queryKey: ['page'] })
      toast.success('Attachment deleted')
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || 'Failed to delete attachment')
    },
  })

  const handleUpload = async (file) => {
    let currentPageId = pageId

    // If no pageId, try to auto-save the page first
    if (!currentPageId && onAutoSave) {
      const newPage = await onAutoSave()
      if (!newPage) {
        return // Auto-save failed, message already shown
      }
      currentPageId = newPage.id
    }

    if (!currentPageId) {
      toast.warning('Please save the page first before adding attachments')
      return
    }

    uploadMutation.mutate({ file, targetPageId: currentPageId })
  }

  const handleDelete = (id) => {
    deleteMutation.mutate(id)
  }

  const attachmentCount = attachments.length + Object.keys(uploadProgress).length

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800"
      >
        <div className="flex items-center gap-2">
          <Paperclip className="h-5 w-5 text-gray-500 dark:text-gray-400" />
          <span className="font-medium text-gray-900 dark:text-white">
            Attachments
          </span>
          {attachmentCount > 0 && (
            <span className="px-2 py-0.5 text-xs bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400 rounded-full">
              {attachmentCount}
            </span>
          )}
        </div>
        <ChevronDown
          className={`h-5 w-5 text-gray-500 dark:text-gray-400 transition-transform ${
            isExpanded ? 'rotate-180' : ''
          }`}
        />
      </button>

      {/* Content */}
      {isExpanded && (
        <div className="p-4 space-y-4">
          {/* Show message if no pageId */}
          {!pageId && !readOnly && (
            <div className="flex items-center gap-2 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
              <AlertCircle className="h-5 w-5 text-blue-500 flex-shrink-0" />
              <p className="text-sm text-blue-700 dark:text-blue-300">
                {onAutoSave
                  ? 'Add attachments to automatically save the page as a draft.'
                  : 'Save the page first to add attachments.'}
              </p>
            </div>
          )}

          {/* Upload zone (only in edit mode) */}
          {!readOnly && (
            <AttachmentUploadZone
              onUpload={handleUpload}
              uploadProgress={uploadProgress}
              disabled={(!pageId && !onAutoSave) || uploadMutation.isPending}
              compact
            />
          )}

          {/* Loading state */}
          {isLoading && (
            <div className="flex justify-center py-4">
              <LoadingSpinner />
            </div>
          )}

          {/* Attachment list */}
          {!isLoading && attachments.length > 0 && (
            <div className="space-y-2">
              {attachments.map((attachment) => (
                <AttachmentItem
                  key={attachment.id}
                  attachment={attachment}
                  onDelete={readOnly ? null : handleDelete}
                  onInsert={readOnly ? null : onInsert}
                  readOnly={readOnly}
                />
              ))}
            </div>
          )}

          {/* Empty state */}
          {!isLoading && attachments.length === 0 && pageId && (
            <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
              No attachments yet.
              {!readOnly && ' Drag and drop files or click to upload.'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

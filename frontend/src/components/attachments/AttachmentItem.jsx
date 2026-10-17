import { useEffect, useState } from 'react'
import { Download, Trash2, ExternalLink, X, Plus } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { getFileIcon, formatFileSize } from './constants'
import { attachmentsApi } from '../../services/api'

export default function AttachmentItem({
  attachment,
  onDelete,
  onInsert,
  readOnly = false,
}) {
  const [showPreview, setShowPreview] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [previewUrl, setPreviewUrl] = useState(null)

  const FileIcon = getFileIcon(attachment.mime_type)
  const isImage = attachment.mime_type?.startsWith('image/')

  useEffect(() => {
    if (!isImage) return undefined
    let cancelled = false
    let url
    attachmentsApi.view(attachment.id).then((res) => {
      if (cancelled) return
      url = URL.createObjectURL(res.data)
      setPreviewUrl(url)
    }).catch(() => {})
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
      setPreviewUrl(null)
    }
  }, [attachment.id, isImage])

  const handleDownload = () => {
    attachmentsApi.download(attachment.id).then((res) => {
      const url = URL.createObjectURL(res.data)
      const link = document.createElement('a')
      link.href = url
      link.download = attachment.filename || 'attachment'
      link.click()
      URL.revokeObjectURL(url)
    }).catch(() => {})
  }

  const handleDelete = () => {
    if (confirmDelete) {
      onDelete(attachment.id)
      setConfirmDelete(false)
    } else {
      setConfirmDelete(true)
      // Auto-dismiss confirmation after 3 seconds
      setTimeout(() => setConfirmDelete(false), 3000)
    }
  }

  return (
    <>
      <div className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-gray-800 rounded-lg group hover:bg-gray-100 dark:hover:bg-gray-750">
        {/* Thumbnail or icon */}
        <div className="flex-shrink-0">
          {isImage ? (
            <button
              onClick={() => setShowPreview(true)}
              className="w-10 h-10 rounded overflow-hidden bg-gray-200 dark:bg-gray-700 hover:ring-2 hover:ring-shizuha-500"
            >
              <img
                src={previewUrl || undefined}
                alt={attachment.filename}
                className="w-full h-full object-cover"
              />
            </button>
          ) : (
            <div className="w-10 h-10 rounded bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
              <FileIcon className="h-5 w-5 text-gray-500 dark:text-gray-400" />
            </div>
          )}
        </div>

        {/* File info */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
            {attachment.filename}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {formatFileSize(attachment.file_size)}
            {' • '}
            {formatDistanceToNow(new Date(attachment.created_at), { addSuffix: true })}
          </p>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {/* Insert button (only in editor) */}
          {onInsert && (
            <button
              onClick={() => onInsert(attachment)}
              className="p-1.5 text-gray-500 hover:text-shizuha-600 dark:text-gray-400 dark:hover:text-shizuha-400 rounded hover:bg-white dark:hover:bg-gray-700"
              title="Insert into content"
            >
              <Plus className="h-4 w-4" />
            </button>
          )}

          {/* Preview button (for images) */}
          {isImage && (
            <button
              onClick={() => setShowPreview(true)}
              className="p-1.5 text-gray-500 hover:text-shizuha-600 dark:text-gray-400 dark:hover:text-shizuha-400 rounded hover:bg-white dark:hover:bg-gray-700"
              title="Preview"
            >
              <ExternalLink className="h-4 w-4" />
            </button>
          )}

          {/* Download button */}
          <button
            onClick={handleDownload}
            className="p-1.5 text-gray-500 hover:text-shizuha-600 dark:text-gray-400 dark:hover:text-shizuha-400 rounded hover:bg-white dark:hover:bg-gray-700"
            title="Download"
          >
            <Download className="h-4 w-4" />
          </button>

          {/* Delete button (only when not readOnly) */}
          {!readOnly && onDelete && (
            <button
              onClick={handleDelete}
              className={`p-1.5 rounded hover:bg-white dark:hover:bg-gray-700 ${
                confirmDelete
                  ? 'text-red-600 dark:text-red-400'
                  : 'text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400'
              }`}
              title={confirmDelete ? 'Click again to confirm' : 'Delete'}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {/* Image preview modal */}
      {showPreview && isImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
          onClick={() => setShowPreview(false)}
        >
          <button
            onClick={() => setShowPreview(false)}
            className="absolute top-4 right-4 p-2 text-white/80 hover:text-white bg-black/50 rounded-full"
          >
            <X className="h-6 w-6" />
          </button>
          <img
            src={previewUrl || undefined}
            alt={attachment.filename}
            className="max-w-[90vw] max-h-[90vh] object-contain"
            onClick={(e) => e.stopPropagation()}
          />
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 px-4 py-2 bg-black/50 rounded-lg">
            <p className="text-white text-sm">{attachment.filename}</p>
          </div>
        </div>
      )}
    </>
  )
}

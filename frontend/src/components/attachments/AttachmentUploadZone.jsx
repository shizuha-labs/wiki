import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, X, CheckCircle, AlertCircle } from 'lucide-react'
import { MAX_FILE_SIZE, validateFile, formatFileSize, getFileIcon } from './constants'

export default function AttachmentUploadZone({
  onUpload,
  uploadProgress = {},
  disabled = false,
  compact = false,
}) {
  const onDrop = useCallback((acceptedFiles) => {
    if (disabled) return

    acceptedFiles.forEach((file) => {
      const errors = validateFile(file)
      if (errors.length === 0) {
        onUpload(file)
      }
    })
  }, [onUpload, disabled])

  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({
    onDrop,
    disabled,
    maxSize: MAX_FILE_SIZE,
    multiple: true,
  })

  const uploadingFiles = Object.entries(uploadProgress)

  return (
    <div className="space-y-3">
      {/* Drop zone */}
      <div
        {...getRootProps()}
        className={`
          border-2 border-dashed rounded-lg transition-colors cursor-pointer
          ${isDragActive
            ? 'border-shizuha-500 bg-shizuha-50 dark:bg-shizuha-900/20'
            : 'border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500'
          }
          ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
          ${compact ? 'p-4' : 'p-6'}
        `}
      >
        <input {...getInputProps()} />
        <div className={`flex flex-col items-center gap-2 ${compact ? '' : 'py-2'}`}>
          <Upload className={`text-gray-400 ${compact ? 'h-6 w-6' : 'h-8 w-8'}`} />
          {isDragActive ? (
            <p className="text-sm text-shizuha-600 dark:text-shizuha-400 font-medium">
              Drop files here...
            </p>
          ) : (
            <>
              <p className={`text-center text-gray-600 dark:text-gray-400 ${compact ? 'text-xs' : 'text-sm'}`}>
                <span className="font-medium text-shizuha-600 dark:text-shizuha-400">
                  Click to upload
                </span>
                {' '}or drag and drop
              </p>
              {!compact && (
                <p className="text-xs text-gray-500 dark:text-gray-500">
                  Maximum file size: {formatFileSize(MAX_FILE_SIZE)}
                </p>
              )}
            </>
          )}
        </div>
      </div>

      {/* File rejections */}
      {fileRejections.length > 0 && (
        <div className="space-y-1">
          {fileRejections.map(({ file, errors }) => (
            <div
              key={file.name}
              className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400"
            >
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              <span className="truncate">{file.name}:</span>
              <span>{errors.map(e => e.message).join(', ')}</span>
            </div>
          ))}
        </div>
      )}

      {/* Upload progress */}
      {uploadingFiles.length > 0 && (
        <div className="space-y-2">
          {uploadingFiles.map(([filename, progress]) => {
            const FileIcon = getFileIcon()
            const isComplete = progress === 100
            const isError = progress === -1

            return (
              <div
                key={filename}
                className="flex items-center gap-3 p-2 bg-gray-50 dark:bg-gray-800 rounded-lg"
              >
                <FileIcon className="h-5 w-5 text-gray-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-900 dark:text-white truncate">
                    {filename}
                  </p>
                  {!isComplete && !isError && (
                    <div className="mt-1 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-shizuha-600 transition-all duration-300"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  )}
                </div>
                <div className="flex-shrink-0">
                  {isComplete && (
                    <CheckCircle className="h-5 w-5 text-green-500" />
                  )}
                  {isError && (
                    <AlertCircle className="h-5 w-5 text-red-500" />
                  )}
                  {!isComplete && !isError && (
                    <span className="text-xs text-gray-500">{progress}%</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

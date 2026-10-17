import {
  File,
  Image,
  FileText,
  Film,
  Music,
  Archive,
  Code,
  Table,
  MonitorPlay,
} from 'lucide-react'

// Maximum file size in bytes (50MB)
export const MAX_FILE_SIZE = 50 * 1024 * 1024

// Allowed MIME types for attachments
export const ALLOWED_MIME_TYPES = {
  // Images
  'image/jpeg': true,
  'image/png': true,
  'image/gif': true,
  'image/webp': true,
  'image/svg+xml': true,
  'image/bmp': true,
  // Documents
  'application/pdf': true,
  'application/msword': true,
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': true,
  'application/vnd.ms-excel': true,
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': true,
  'application/vnd.ms-powerpoint': true,
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': true,
  'text/plain': true,
  'text/csv': true,
  'text/markdown': true,
  // Code files
  'text/javascript': true,
  'application/javascript': true,
  'text/css': true,
  'text/html': true,
  'application/json': true,
  'text/xml': true,
  'application/xml': true,
  // Archives
  'application/zip': true,
  'application/x-rar-compressed': true,
  'application/x-7z-compressed': true,
  'application/gzip': true,
  'application/x-tar': true,
  // Audio/Video
  'audio/mpeg': true,
  'audio/wav': true,
  'audio/ogg': true,
  'video/mp4': true,
  'video/webm': true,
  'video/quicktime': true,
}

// Get icon component for a MIME type
export function getFileIcon(mimeType) {
  if (!mimeType) return File

  if (mimeType.startsWith('image/')) return Image
  if (mimeType.startsWith('video/')) return Film
  if (mimeType.startsWith('audio/')) return Music

  if (mimeType.includes('pdf') || mimeType.includes('word') || mimeType === 'text/plain') {
    return FileText
  }

  if (mimeType.includes('excel') || mimeType.includes('spreadsheet') || mimeType === 'text/csv') {
    return Table
  }

  if (mimeType.includes('powerpoint') || mimeType.includes('presentation')) {
    return MonitorPlay
  }

  if (mimeType.includes('zip') || mimeType.includes('rar') || mimeType.includes('7z') ||
      mimeType.includes('gzip') || mimeType.includes('tar')) {
    return Archive
  }

  if (mimeType.includes('javascript') || mimeType.includes('json') || mimeType.includes('xml') ||
      mimeType.includes('css') || mimeType.includes('html') || mimeType === 'text/markdown') {
    return Code
  }

  return File
}

// Format file size in human-readable format
export function formatFileSize(bytes) {
  if (bytes === 0) return '0 B'

  const units = ['B', 'KB', 'MB', 'GB']
  const k = 1024
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${units[i]}`
}

// Validate file for upload
export function validateFile(file) {
  const errors = []

  if (file.size > MAX_FILE_SIZE) {
    errors.push(`File size (${formatFileSize(file.size)}) exceeds maximum of ${formatFileSize(MAX_FILE_SIZE)}`)
  }

  // Allow files with no type or unknown types (be permissive)
  // The backend will do final validation

  return errors
}

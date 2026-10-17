import { useAuth } from '../contexts/AuthContext'

export default function ProtectedRoute({ children }) {
  const { isAuthenticated, isLoading, getLoginUrl } = useAuth()

  if (isLoading) {
    return null
  }

  if (!isAuthenticated) {
    // Allow anonymous viewing of space/page VIEW routes — the backend enforces
    // visibility (public spaces return content to anonymous users; private → 403,
    // surfaced by the page component). Edit/admin/dashboard routes still need login.
    const p = window.location.pathname || ''
    const isPublicView = /\/spaces\/[^/]+(?:\/pages\/[^/]+)?\/?$/.test(p)
    if (isPublicView) return children
    window.location.href = getLoginUrl()
    return null
  }

  return children
}

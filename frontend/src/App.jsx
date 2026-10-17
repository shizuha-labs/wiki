import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './contexts/AuthContext'
import Layout from './components/Layout'
import LoadingSpinner from './components/LoadingSpinner'
import ProtectedRoute from './components/ProtectedRoute'
import Dashboard from './pages/Dashboard'
import SpaceList from './pages/SpaceList'
import SpaceView from './pages/SpaceView'
import SpaceSettings from './pages/SpaceSettings'
import PageView from './pages/PageView'
import PageEditor from './pages/PageEditor'
import CanonicalPageRedirect from './pages/CanonicalPageRedirect'
import Search from './pages/Search'
import LabelBrowse from './pages/LabelBrowse'
import Settings from './pages/Settings'
import { ShizuhaChatWidget } from './components/chat'

function LeaveForAtlas() {
  useEffect(() => {
    const tail = window.location.pathname.replace(/^\/wiki\/atlas\/?/, '/atlas/')
    window.location.replace(`${tail}${window.location.search}${window.location.hash}`)
  }, [])
  return <div className="min-h-screen flex items-center justify-center">Opening Atlas…</div>
}

function App() {
  const { isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <>
      <Routes>
        <Route path="/atlas" element={<LeaveForAtlas />} />
        <Route path="/atlas/*" element={<LeaveForAtlas />} />
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Dashboard />} />
          <Route path="spaces" element={<SpaceList />} />
          <Route path="spaces/:spaceKey" element={<SpaceView />} />
          <Route path="spaces/:spaceKey/settings" element={<SpaceSettings />} />
          <Route path="spaces/:spaceKey/pages/new" element={<PageEditor />} />
          <Route path="spaces/:spaceKey/pages/:pageSlug" element={<PageView />} />
          <Route path="spaces/:spaceKey/labels" element={<LabelBrowse />} />
          <Route path="spaces/:spaceKey/labels/:labelId" element={<LabelBrowse />} />
          <Route path="spaces/:spaceKey/pages/:pageSlug/edit" element={<PageEditor />} />
          <Route path=":pageId" element={<CanonicalPageRedirect />} />
          <Route path="search" element={<Search />} />
          <Route path="settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <div className="wiki-chrome">
        <ShizuhaChatWidget
          sourceService="wiki"
          welcomeMessage="Hello! I can help you search documentation, create new pages, and find information across your wiki."
          showToolCalls={true}
        />
      </div>
    </>
  )
}

export default App

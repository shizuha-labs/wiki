import { useState } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, Plus, Users, FileText, Archive } from 'lucide-react'
import { useSpace } from '../contexts/SpaceContext'
import LoadingSpinner from '../components/LoadingSpinner'
import { VisibilitySelector } from '../components/settings'

export default function SpaceList() {
  const { spaces, createSpace, spacesLoading } = useSpace()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newSpace, setNewSpace] = useState({ key: '', name: '', description: '', space_type: 'documentation', visibility: 'org' })
  const [creating, setCreating] = useState(false)

  const handleCreateSpace = async (e) => {
    e.preventDefault()
    setCreating(true)
    try {
      await createSpace(newSpace)
      setShowCreateModal(false)
      setNewSpace({ key: '', name: '', description: '', space_type: 'documentation', visibility: 'org' })
    } catch (error) {
      console.error('Failed to create space:', error)
    }
    setCreating(false)
  }

  if (spacesLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Spaces</h1>
          <p className="mt-1 text-gray-600 dark:text-gray-400">
            Organize your documentation into spaces
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Create Space
        </button>
      </div>

      {/* Space grid */}
      {spaces.length > 0 ? (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {spaces.map((space) => (
            <Link
              key={space.id}
              to={`/spaces/${space.key}`}
              className="block p-6 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600 transition-colors"
            >
              <div className="flex items-start gap-4">
                <div
                  className="w-12 h-12 rounded-lg flex items-center justify-center"
                  style={{ backgroundColor: space.color + '20' }}
                >
                  <BookOpen className="h-6 w-6" style={{ color: space.color }} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-gray-900 dark:text-white truncate">
                      {space.name}
                    </h3>
                    {space.is_archived && (
                      <Archive className="h-4 w-4 text-gray-400" />
                    )}
                  </div>
                  <p className="text-sm text-gray-500 dark:text-gray-400">{space.key}</p>
                  {space.description && (
                    <p className="mt-2 text-sm text-gray-600 dark:text-gray-300 line-clamp-2">
                      {space.description}
                    </p>
                  )}
                  <div className="mt-4 flex items-center gap-4 text-sm text-gray-500 dark:text-gray-400">
                    <span className="flex items-center gap-1">
                      <FileText className="h-4 w-4" />
                      {space.pages_count || 0} pages
                    </span>
                    <span className="flex items-center gap-1">
                      <Users className="h-4 w-4" />
                      {space.members_count || 0} members
                    </span>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <BookOpen className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-white">No spaces yet</h3>
          <p className="mt-2 text-gray-500 dark:text-gray-400">
            Create your first space to start documenting.
          </p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="mt-4 inline-flex items-center px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700"
          >
            <Plus className="h-4 w-4 mr-2" />
            Create Space
          </button>
        </div>
      )}

      {/* Create modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Create New Space
            </h2>
            <form onSubmit={handleCreateSpace} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Space Key
                </label>
                <input
                  type="text"
                  value={newSpace.key}
                  onChange={(e) => setNewSpace({ ...newSpace, key: e.target.value.toUpperCase() })}
                  placeholder="e.g., ENG, HR, DOCS"
                  maxLength={10}
                  required
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-shizuha-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Space Name
                </label>
                <input
                  type="text"
                  value={newSpace.name}
                  onChange={(e) => setNewSpace({ ...newSpace, name: e.target.value })}
                  placeholder="e.g., Engineering Documentation"
                  required
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-shizuha-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  value={newSpace.description}
                  onChange={(e) => setNewSpace({ ...newSpace, description: e.target.value })}
                  placeholder="What is this space about?"
                  rows={3}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-shizuha-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Space Type
                </label>
                <select
                  value={newSpace.space_type}
                  onChange={(e) => setNewSpace({ ...newSpace, space_type: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-shizuha-500"
                >
                  <option value="documentation">Documentation</option>
                  <option value="knowledge_base">Knowledge Base</option>
                  <option value="project">Project</option>
                  <option value="team">Team</option>
                  <option value="personal">Personal</option>
                </select>
              </div>
              <VisibilitySelector
                value={newSpace.visibility}
                onChange={(visibility) => setNewSpace({ ...newSpace, visibility })}
              />
              <div className="flex justify-end gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 disabled:opacity-50"
                >
                  {creating ? 'Creating...' : 'Create Space'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

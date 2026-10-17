import { useQuery } from '@tanstack/react-query'
import { useParams, Link } from 'react-router-dom'
import { FileText, Plus, FolderOpen, Clock, Settings } from 'lucide-react'
import { spacesApi, pagesApi } from '../services/api'
import { useAuth } from '../contexts/AuthContext'
import LoadingSpinner from '../components/LoadingSpinner'
import PageTree from '../components/PageTree'
import { formatDistanceToNow } from 'date-fns'

const VISIBILITY_LABELS = { private: 'Private', org: 'Organization', public: 'Public' }

export default function SpaceView() {
  const { spaceKey } = useParams()
  const { user } = useAuth()

  // Fetch space details
  const { data: space, isLoading: spaceLoading } = useQuery({
    queryKey: ['space', spaceKey],
    queryFn: async () => {
      const response = await spacesApi.get(spaceKey)
      return response.data
    },
  })

  // Fetch page tree
  const { data: pageTree = [], isLoading: treeLoading } = useQuery({
    queryKey: ['space', spaceKey, 'tree'],
    queryFn: async () => {
      const response = await spacesApi.getTree(spaceKey)
      return response.data
    },
    enabled: !!space,
  })

  // Fetch recent pages in space
  const { data: recentPages = [] } = useQuery({
    queryKey: ['pages', spaceKey, 'recent'],
    queryFn: async () => {
      const response = await pagesApi.list({ space_key: spaceKey, status: 'published', ordering: '-updated_at' })
      return response.data.results || response.data
    },
    enabled: !!space,
  })

  // Fetch members to check if user is admin
  const { data: members = [] } = useQuery({
    queryKey: ['space', spaceKey, 'members'],
    queryFn: async () => {
      const response = await spacesApi.getMembers(spaceKey)
      return response.data
    },
    enabled: !!space,
  })

  // Fetch user permissions for this space
  const { data: permissions } = useQuery({
    queryKey: ['space', spaceKey, 'permissions'],
    queryFn: async () => {
      const response = await spacesApi.getPermissions(spaceKey)
      return response.data
    },
    enabled: !!space,
  })

  // Check if current user is a space admin (via permissions endpoint, which handles superusers)
  const isSpaceAdmin = permissions && ['owner', 'admin'].includes(permissions.role)

  if (spaceLoading || treeLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!space) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Space not found</h2>
        <Link to="/spaces" className="text-shizuha-600 hover:underline mt-2 inline-block">
          Back to spaces
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Space header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <div
            className="w-16 h-16 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: space.color + '20' }}
          >
            <FolderOpen className="h-8 w-8" style={{ color: space.color }} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{space.name}</h1>
            <p className="text-gray-500 dark:text-gray-400">{space.key}</p>
            {space.description && (
              <p className="mt-1 text-gray-600 dark:text-gray-300">{space.description}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {isSpaceAdmin && (
            <Link
              to={`/spaces/${spaceKey}/settings`}
              className="flex items-center gap-2 px-4 py-2 text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              <Settings className="h-4 w-4" />
              Settings
            </Link>
          )}
          <Link
            to={`/spaces/${spaceKey}/pages/new`}
            className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700"
          >
            <Plus className="h-4 w-4" />
            New Page
          </Link>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Page tree */}
        <div className="lg:col-span-2">
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
              <h2 className="font-semibold text-gray-900 dark:text-white">Pages</h2>
            </div>
            <div className="p-4">
              {pageTree.length > 0 ? (
                <PageTree pages={pageTree} spaceKey={spaceKey} permissions={permissions} enableDragDrop />
              ) : (
                <div className="text-center py-8">
                  <FileText className="mx-auto h-12 w-12 text-gray-400" />
                  <p className="mt-4 text-gray-500 dark:text-gray-400">No pages yet</p>
                  <Link
                    to={`/spaces/${spaceKey}/pages/new`}
                    className="mt-2 inline-flex items-center text-shizuha-600 hover:underline"
                  >
                    <Plus className="h-4 w-4 mr-1" />
                    Create your first page
                  </Link>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Recent activity */}
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
              <h3 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                <Clock className="h-4 w-4" />
                Recent Activity
              </h3>
            </div>
            <div className="divide-y divide-gray-200 dark:divide-gray-700">
              {recentPages.slice(0, 5).map((page) => (
                <Link
                  key={page.id}
                  to={`/spaces/${spaceKey}/pages/${page.slug}`}
                  className="block px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                >
                  <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {page.title}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {formatDistanceToNow(new Date(page.updated_at), { addSuffix: true })}
                  </p>
                </Link>
              ))}
              {recentPages.length === 0 && (
                <p className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                  No recent activity
                </p>
              )}
            </div>
          </div>

          {/* Space info */}
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
            <h3 className="font-semibold text-gray-900 dark:text-white mb-3">Space Info</h3>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-gray-500 dark:text-gray-400">Type</dt>
                <dd className="text-gray-900 dark:text-white capitalize">{space.space_type?.replace('_', ' ')}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500 dark:text-gray-400">Visibility</dt>
                <dd className="text-gray-900 dark:text-white">{VISIBILITY_LABELS[space.visibility] || space.visibility}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500 dark:text-gray-400">Pages</dt>
                <dd className="text-gray-900 dark:text-white">{space.pages_count || 0}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500 dark:text-gray-400">Members</dt>
                <dd className="text-gray-900 dark:text-white">{space.members_count || 0}</dd>
              </div>
            </dl>
          </div>
        </div>
      </div>
    </div>
  )
}


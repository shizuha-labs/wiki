import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { BookOpen, FileText, Clock, Star, Users } from 'lucide-react'
import { pagesApi } from '../services/api'
import { useSpace } from '../contexts/SpaceContext'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatDistanceToNow } from 'date-fns'

export default function Dashboard() {
  const { spaces, currentSpace, isLoading: spaceLoading } = useSpace()

  // Fetch recent pages
  const { data: recentPages = [], isLoading: pagesLoading } = useQuery({
    queryKey: ['pages', 'recent'],
    queryFn: async () => {
      const response = await pagesApi.list({ status: 'published', ordering: '-updated_at' })
      return response.data.results || response.data
    },
  })

  if (spaceLoading || pagesLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Welcome header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Welcome to Shizuha Wiki
        </h1>
        <p className="mt-1 text-gray-600 dark:text-gray-400">
          Your team's knowledge base and documentation hub
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={BookOpen}
          label="Spaces"
          value={spaces.length}
          color="bg-blue-500"
        />
        <StatCard
          icon={FileText}
          label="Pages"
          value={recentPages.length}
          color="bg-green-500"
        />
        <StatCard
          icon={Users}
          label="Contributors"
          value="-"
          color="bg-purple-500"
        />
        <StatCard
          icon={Star}
          label="Favorites"
          value="-"
          color="bg-yellow-500"
        />
      </div>

      {/* Spaces quick access */}
      {spaces.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-gray-500" />
              Your Spaces
            </h2>
            <Link
              to="/spaces"
              className="text-sm text-shizuha-600 hover:text-shizuha-700 dark:text-shizuha-400"
            >
              View all
            </Link>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {spaces.slice(0, 8).map((space) => (
              <Link
                key={space.id}
                to={`/spaces/${space.key}`}
                className="flex items-center gap-3 p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600 transition-colors"
              >
                <span
                  className="w-4 h-4 rounded-full flex-shrink-0"
                  style={{ backgroundColor: space.color }}
                />
                <div className="min-w-0">
                  <p className="font-medium text-gray-900 dark:text-white truncate">
                    {space.name}
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {space.key}
                  </p>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Recent pages */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Clock className="h-5 w-5 text-gray-500" />
            Recently Updated
          </h2>
        </div>
        {recentPages.length > 0 ? (
          <div className="space-y-2">
            {recentPages.slice(0, 10).map((page) => (
              <Link
                key={page.id}
                to={`/spaces/${page.space_key}/pages/${page.slug}`}
                className="flex items-center justify-between p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <FileText className="h-5 w-5 text-gray-400 flex-shrink-0" />
                  <div className="min-w-0">
                    <p className="font-medium text-gray-900 dark:text-white truncate">
                      {page.title}
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {page.space_name}
                    </p>
                  </div>
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 flex-shrink-0">
                  {formatDistanceToNow(new Date(page.updated_at), { addSuffix: true })}
                </p>
              </Link>
            ))}
          </div>
        ) : (
          <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            <FileText className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-white">No pages yet</h3>
            <p className="mt-2 text-gray-500 dark:text-gray-400">
              Get started by creating your first wiki page.
            </p>
            {currentSpace && (
              <Link
                to={`/spaces/${currentSpace.key}/pages/new`}
                className="mt-4 inline-flex items-center px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700"
              >
                Create Page
              </Link>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-center gap-3">
        <div className={`${color} p-2 rounded-lg`}>
          <Icon className="h-5 w-5 text-white" />
        </div>
        <div>
          <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
        </div>
      </div>
    </div>
  )
}

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Tag } from 'lucide-react'
import { labelsApi } from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'

export default function LabelBrowse() {
  const { spaceKey, labelId } = useParams()
  const { data: labels = [], isLoading: labelsLoading } = useQuery({
    queryKey: ['labels', 'cloud', spaceKey],
    queryFn: async () => {
      const response = await labelsApi.cloud({ space_key: spaceKey })
      return response.data
    },
  })

  const selected = useMemo(() => labels.find((label) => String(label.id) === String(labelId)), [labels, labelId])

  const { data: pagesPayload, isLoading: pagesLoading } = useQuery({
    queryKey: ['labels', labelId, 'pages', spaceKey],
    enabled: Boolean(labelId),
    queryFn: async () => {
      const response = await labelsApi.pages(labelId, { space_key: spaceKey })
      return response.data
    },
  })
  const pages = pagesPayload?.results || pagesPayload || []

  if (labelsLoading) return <LoadingSpinner />

  const maxCount = Math.max(1, ...labels.map((label) => label.pages_count || 0))

  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
          <Tag className="h-8 w-8 text-shizuha-600" />
          Browse by label
        </h1>
        <p className="text-gray-600 dark:text-gray-400 mt-2">Explore pages in {spaceKey} by shared labels.</p>
      </div>

      {labels.length === 0 ? (
        <p className="text-gray-500 dark:text-gray-400">No labels are used in this space yet.</p>
      ) : (
        <div className="flex flex-wrap gap-3 mb-10">
          {labels.map((label) => {
            const weight = 0.85 + ((label.pages_count || 0) / maxCount) * 0.65
            return (
              <Link
                key={label.id}
                to={`/spaces/${spaceKey}/labels/${label.id}`}
                className={`rounded-full px-3 py-1.5 border transition ${String(label.id) === String(labelId) ? 'border-shizuha-500 bg-shizuha-50 dark:bg-shizuha-900/30' : 'border-gray-200 dark:border-gray-700 hover:border-shizuha-300'}`}
                style={{ fontSize: `${weight}rem`, color: label.color }}
              >
                {label.name}
                <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">{label.pages_count}</span>
              </Link>
            )
          })}
        </div>
      )}

      {labelId && (
        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
            Pages labelled {selected ? selected.name : '…'}
          </h2>
          {pagesLoading ? <LoadingSpinner /> : pages.length === 0 ? (
            <p className="text-gray-500 dark:text-gray-400">No published pages found for this label.</p>
          ) : (
            <div className="grid md:grid-cols-2 gap-4">
              {pages.map((page) => (
                <Link
                  key={page.id}
                  to={`/spaces/${page.space_key || spaceKey}/pages/${page.slug}`}
                  className="block p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600"
                >
                  <h3 className="font-medium text-gray-900 dark:text-white">{page.title}</h3>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{page.space_key || spaceKey}</p>
                </Link>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}

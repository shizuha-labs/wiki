import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Navigate, useLocation, useParams } from 'react-router-dom'
import LoadingSpinner from '../components/LoadingSpinner'
import { pagesApi } from '../services/api'
import {
  canonicalPageDocumentPath,
  canonicalPagePath,
} from '../utils/canonicalPage'

const ORG_ID_KEY = 'shizuha_organization_id'

export default function CanonicalPageRedirect() {
  const { pageId } = useParams()
  const location = useLocation()

  const {
    data: page,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['canonical-page', pageId],
    queryFn: async () => {
      // Resolve across every membership: a bare UUID link names no tenant.
      const response = await pagesApi.getAcrossOrganizations(pageId)
      return response.data
    },
    retry: (failureCount, error) => {
      const status = error?.response?.status
      return status !== 403 && status !== 404 && failureCount < 1
    },
  })

  // Resolving the page is only half the job. The canonical route we hand off to
  // re-fetches through the normal org-scoped client, so if the page lives in a
  // different tenant than the one currently selected we must adopt its
  // organization first — otherwise the deep link resolves here and then 404s
  // one navigation later. A full document load is deliberate: it re-bootstraps
  // AuthContext so the switcher and the API agree on the tenant.
  const resolvedOrgId =
    page?.organization_id != null ? String(page.organization_id) : null
  const needsOrganizationSwitch =
    resolvedOrgId !== null && resolvedOrgId !== localStorage.getItem(ORG_ID_KEY)

  useEffect(() => {
    if (!needsOrganizationSwitch || !page?.space_key || !page?.slug) {
      return
    }
    localStorage.setItem(ORG_ID_KEY, resolvedOrgId)
    window.location.assign(
      `${canonicalPageDocumentPath(page)}${location.search}${location.hash}`,
    )
  }, [
    needsOrganizationSwitch,
    resolvedOrgId,
    page,
    location.search,
    location.hash,
  ])

  if (isLoading || (needsOrganizationSwitch && page?.space_key && page?.slug)) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (isError || !page?.space_key || !page?.slug) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
          Page unavailable
        </h2>
        <p className="mt-2 text-gray-500 dark:text-gray-400">
          The page does not exist or is not available in this organization.
        </p>
      </div>
    )
  }

  const canonicalPath = canonicalPagePath(page)

  return (
    <Navigate
      to={`${canonicalPath}${location.search}${location.hash}`}
      replace
    />
  )
}

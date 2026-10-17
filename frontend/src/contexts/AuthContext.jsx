import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import api from '../services/api'
import { hydrateDiagramPrefsFromAccount } from '../utils/diagramPrefs'

const AuthContext = createContext(null)

// Token storage keys
const ACCESS_TOKEN_KEY = 'shizuha_access_token'
const REFRESH_TOKEN_KEY = 'shizuha_refresh_token'
const USER_KEY = 'shizuha_user'
const ORG_ID_KEY = 'shizuha_organization_id'

const getRequestedOrganizationId = () => {
  const value = new URLSearchParams(window.location.search).get('organization')
  return value ? String(value) : null
}

// Shizuha ID API client for auth operations (tokens are issued by shizuha-id)
const idApi = axios.create({
  baseURL: '/id/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Fetch user's organizations from shizuha-admin.
// PLAT-8302: an authz failure (401/403) is NOT an empty membership set —
// collapsing every error into [] made the sidebar claim "No Organization"
// from a failed request. Returns { orgs, error } so the UI can render a
// truthful access-denied state; error = { status, code } | null.
async function fetchUserOrganizations(token) {
  try {
    const response = await axios.get('/admin/api/organizations/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      }
    })
    return { orgs: response.data.results || response.data || [], error: null }
  } catch (error) {
    const status = error.response?.status
    const code = error.response?.data?.code || error.response?.data?.detail || error.message
    console.error('Failed to fetch organizations:', error)
    return { orgs: [], error: { status, code } }
  }
}

// Get login URL - redirect to unified Shizuha ID login
const getLoginUrl = () => {
  const currentPath = `${window.location.pathname}${window.location.search}`
  const continueUrl = encodeURIComponent(currentPath || '/wiki/')
  return `/id/login?continue=${continueUrl}`
}

// Public, login-free VIEW routes (public spaces/pages). On these we must NOT
// force a login redirect when an auth-required side request (user/notifications)
// returns 401 for an anonymous visitor — the page itself renders from public data.
const isPublicViewPath = () =>
  /\/spaces\/[^/]+(?:\/pages\/[^/]+)?\/?$/.test(window.location.pathname || '')

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [organization, setOrganization] = useState(null)
  const [organizations, setOrganizations] = useState([])
  const [orgsError, setOrgsError] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isAuthenticated, setIsAuthenticated] = useState(false)

  // Initialize auth state from localStorage
  useEffect(() => {
    const initAuth = async () => {
      const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY)
      const storedUser = localStorage.getItem(USER_KEY)
      const storedOrgId = localStorage.getItem(ORG_ID_KEY)
      const requestedOrgId = getRequestedOrganizationId()

      if (accessToken && storedUser) {
        try {
          // Access-token enabled_services is a login snapshot. Rebuild it
          // from Identity on every boot so a grant applies on reload
          // (Ctrl+Shift+R) instead of requiring logout.
          let token = accessToken
          const existingRefresh = localStorage.getItem(REFRESH_TOKEN_KEY)
          if (existingRefresh) {
            try {
              token = await refreshAccessToken(existingRefresh)
            } catch (refreshError) {
              console.warn('Access-token refresh on boot failed; using stored access token', refreshError)
            }
          }

          api.defaults.headers.common['Authorization'] = `Bearer ${token}`
          setUser(JSON.parse(storedUser))
          setIsAuthenticated(true)

          // Fetch orgs and account diagram prefs in parallel so a new browser
          // paints the user's saved look instead of local defaults.
          const [{ orgs, error: orgsFetchError }] = await Promise.all([
            fetchUserOrganizations(token),
            hydrateDiagramPrefsFromAccount().catch(() => {}),
          ])
          setOrganizations(orgs)
          setOrgsError(orgsFetchError)

          // An organization-qualified deep link is authoritative for this
          // navigation. Persist the validated context before rendering the
          // route so its first API request cannot leak the prior app's tenant.
          const selectedOrgId = requestedOrgId || storedOrgId
          if (selectedOrgId && orgs.some(o => String(o.id) === selectedOrgId)) {
            const org = orgs.find(o => String(o.id) === selectedOrgId)
            setOrganization(org)
            localStorage.setItem(ORG_ID_KEY, String(org.id))
          } else if (requestedOrgId) {
            // Fail closed when a deep link names an organization the caller
            // cannot access. Do not silently open a same-key space elsewhere.
            setOrganization(null)
            localStorage.setItem(ORG_ID_KEY, requestedOrgId)
          } else if (orgs.length > 0) {
            const defaultOrg = orgs[0]
            setOrganization(defaultOrg)
            localStorage.setItem(ORG_ID_KEY, String(defaultOrg.id))
          }
        } catch (error) {
          console.error('Token validation failed:', error)
          const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
          if (refreshToken) {
            try {
              await refreshAccessToken(refreshToken)
            } catch {
              clearAuthState()
            }
          } else {
            clearAuthState()
          }
        }
      }
      setIsLoading(false)
    }

    initAuth()
  }, [])

  // Setup axios interceptor for token refresh
  useEffect(() => {
    const interceptor = api.interceptors.response.use(
      (response) => response,
      async (error) => {
        const originalRequest = error.config

        const status = error.response?.status
        const code = error.response?.data?.code
        const serviceDenied = status === 403 && code === 'service_access_denied'
        if ((status === 401 || serviceDenied) && !originalRequest._retry) {
          originalRequest._retry = true

          const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
          if (refreshToken) {
            try {
              const newAccessToken = await refreshAccessToken(refreshToken)
              originalRequest.headers['Authorization'] = `Bearer ${newAccessToken}`
              return api(originalRequest)
            } catch {
              if (status === 401) {
                clearAuthState()
                if (!isPublicViewPath()) window.location.href = getLoginUrl()
              }
            }
          } else if (status === 401) {
            clearAuthState()
            if (!isPublicViewPath()) window.location.href = getLoginUrl()
          }
        }
        return Promise.reject(error)
      }
    )

    return () => api.interceptors.response.eject(interceptor)
  }, [])

  const refreshAccessToken = async (refreshToken) => {
    // Token refresh goes to shizuha-id (the identity provider)
    const response = await idApi.post('/auth/refresh/', { refresh: refreshToken })
    const newAccessToken = response.data.access
    localStorage.setItem(ACCESS_TOKEN_KEY, newAccessToken)
    api.defaults.headers.common['Authorization'] = `Bearer ${newAccessToken}`

    if (response.data.refresh) {
      localStorage.setItem(REFRESH_TOKEN_KEY, response.data.refresh)
    }

    return newAccessToken
  }

  const clearAuthState = () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    localStorage.removeItem(ORG_ID_KEY)
    delete api.defaults.headers.common['Authorization']
    setUser(null)
    setOrganization(null)
    setOrganizations([])
    setIsAuthenticated(false)
  }

  const switchOrganization = (org) => {
    setOrganization(org)
    localStorage.setItem(ORG_ID_KEY, String(org.id))
    // Keep an organization-qualified deep link qualified when the user
    // deliberately switches tenant; otherwise the stale query would override
    // their choice during the reload.
    const url = new URL(window.location.href)
    if (url.searchParams.has('organization')) {
      url.searchParams.set('organization', String(org.id))
      window.location.assign(`${url.pathname}${url.search}${url.hash}`)
      return
    }
    window.location.reload()
  }

  const logout = useCallback(async () => {
    try {
      const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
      if (refreshToken) {
        // Logout goes to shizuha-id (the identity provider)
        await idApi.post('/auth/logout/', { refresh: refreshToken })
      }
    } catch (error) {
      console.error('Logout error:', error)
    } finally {
      clearAuthState()
      window.location.href = '/id/login?continue=/wiki/'
    }
  }, [])

  const value = {
    user,
    isLoading,
    isAuthenticated,
    organization,
    organizations,
    orgsError,
    switchOrganization,
    logout,
    getLoginUrl,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export default AuthContext

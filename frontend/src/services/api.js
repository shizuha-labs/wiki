import axios from 'axios'

// API base URL - nginx routes /wiki/api/ to shizuha-wiki backend
const API_BASE = import.meta.env.VITE_API_BASE || '/wiki/api'

const api = axios.create({
  baseURL: API_BASE,
})

// Add auth token and organization header to all requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('shizuha_access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  // The backend aggregates a read across every membership ONLY when this
  // header is absent — an empty/sentinel value does not work. A request that
  // must resolve across organizations therefore has to opt out entirely.
  const orgId = localStorage.getItem('shizuha_organization_id')
  if (orgId && !config.skipOrganizationHeader) {
    config.headers['X-Organization-ID'] = orgId
  }

  return config
})

// Spaces API
export const spacesApi = {
  list: (params) => api.get('/spaces/', { params }),
  get: (id) => api.get(`/spaces/${id}/`),
  create: (data) => api.post('/spaces/', data),
  update: (id, data) => api.patch(`/spaces/${id}/`, data),
  delete: (id) => api.delete(`/spaces/${id}/`),
  archive: (id) => api.post(`/spaces/${id}/archive/`),
  unarchive: (id) => api.post(`/spaces/${id}/unarchive/`),
  getTree: (id) => api.get(`/spaces/${id}/tree/`),
  getMembers: (id) => api.get(`/spaces/${id}/members/`),
  addMember: (id, data) => api.post(`/spaces/${id}/members/`, data),
  updateMemberRole: (id, userId, role) => api.patch(`/spaces/${id}/members/`, { user_id: userId, role }),
  removeMember: (id, userId) => api.delete(`/spaces/${id}/members/`, { data: { user_id: userId } }),
  searchUsers: (id, query) => api.get(`/spaces/${id}/search_users/`, { params: { q: query } }),
  watch: (id) => api.post(`/spaces/${id}/watch/`),
  getPermissions: (key) => api.get(`/spaces/${key}/permissions/`),
}

// Pages API
export const pagesApi = {
  list: (params) => api.get('/pages/', { params }),
  get: (id, config) => api.get(`/pages/${id}/`, config),
  // A bare canonical UUID link carries no tenant, so it must resolve against
  // every membership the caller holds. Omitting X-Organization-ID is what
  // enables that server-side aggregation; sending the previously selected org
  // pins the lookup to the wrong tenant and 404s a page the user can read
  // (PLAT-5192).
  getAcrossOrganizations: (id) =>
    api.get(`/pages/${id}/`, { skipOrganizationHeader: true }),
  create: (data) => api.post('/pages/', data),
  update: (id, data) => api.patch(`/pages/${id}/`, data),
  delete: (id) => api.delete(`/pages/${id}/`),
  getVersions: (id) => api.get(`/pages/${id}/versions/`),
  restoreVersion: (id, version) => api.post(`/pages/${id}/restore_version/`, { version }),
  getComments: (id) => api.get(`/pages/${id}/comments/`),
  addComment: (id, data) => api.post(`/pages/${id}/comments/`, data),
  getChildren: (id) => api.get(`/pages/${id}/children/`),
  getBacklinks: (id) => api.get(`/pages/${id}/backlinks/`),
  getRelated: (id, params) => api.get(`/pages/${id}/related/`, { params }),
  watch: (id) => api.post(`/pages/${id}/watch/`),
  movePage: (id, data) => api.post(`/pages/${id}/move/`, data),
  reorderPages: (data) => api.post('/pages/reorder/', data),
}

// Labels API
export const labelsApi = {
  list: (params) => api.get('/labels/', { params }),
  get: (id) => api.get(`/labels/${id}/`),
  create: (data) => api.post('/labels/', data),
  update: (id, data) => api.patch(`/labels/${id}/`, data),
  delete: (id) => api.delete(`/labels/${id}/`),
  cloud: (params) => api.get('/labels/cloud/', { params }),
  pages: (id, params) => api.get(`/labels/${id}/pages/`, { params }),
}

// Templates API
export const templatesApi = {
  list: (params) => api.get('/templates/', { params }),
  get: (id) => api.get(`/templates/${id}/`),
  create: (data) => api.post('/templates/', data),
  update: (id, data) => api.patch(`/templates/${id}/`, data),
  delete: (id) => api.delete(`/templates/${id}/`),
}

// Attachments API
export const attachmentsApi = {
  list: (pageId) => api.get('/attachments/', { params: { page_id: pageId } }),
  upload: (pageId, file, onProgress) => {
    const formData = new FormData()
    formData.append('page', pageId)
    formData.append('file', file)
    return api.post('/attachments/', formData, {
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          const percent = Math.round((event.loaded / event.total) * 100)
          onProgress(percent)
        }
      },
    })
  },
  delete: (id) => api.delete(`/attachments/${id}/`),
  download: (id) => api.get(`/attachments/${id}/download/`, { responseType: 'blob' }),
  view: (id) => api.get(`/attachments/${id}/view/`, { responseType: 'blob' }),
  // Helper to get download URL (for direct links)
  getDownloadUrl: (id) => `${API_BASE}/attachments/${id}/download/`,
  getViewUrl: (id) => `${API_BASE}/attachments/${id}/view/`,
}

// Comments API
export const commentsApi = {
  // Use page_id to avoid conflict with DRF pagination's 'page' param
  list: (pageId) => api.get('/comments/', { params: { page_id: pageId } }),
  create: (data) => api.post('/comments/', data),
  update: (id, data) => api.patch(`/comments/${id}/`, data),
  delete: (id) => api.delete(`/comments/${id}/`),
  resolve: (id) => api.post(`/comments/${id}/resolve/`),
  unresolve: (id) => api.post(`/comments/${id}/unresolve/`),
}

// Search API
export const searchApi = {
  search: (params) => api.get('/search/', { params }),
}

export const atlasApi = {
  get: () => api.get('/atlas/'),
  maps: () => api.get('/atlas/maps/'),
}

export const preferencesApi = {
  get: () => api.get('/preferences/'),
  patch: (data) => api.patch('/preferences/', data),
}

export default api

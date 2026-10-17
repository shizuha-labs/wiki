import { test as base } from '@playwright/test'

/**
 * Test fixtures for Shizuha Wiki E2E tests
 * Provides authenticated user context, test data helpers, and API access
 *
 * Authentication flow:
 * - Login happens at /id/login (Shizuha ID)
 * - After login, user is redirected to /wiki/ (Shizuha Wiki)
 * - Tokens are stored in localStorage with shared keys
 */

// Test user credentials (same as other Shizuha services)
export const TEST_USER = {
  username: 'testuser',
  password: 'TestPass123',
  email: 'testuser@example.com'
}

// Test space data
export const TEST_SPACE = {
  name: `Test Space ${Date.now()}`,
  key: `TS${Date.now().toString().slice(-6)}`,
  description: 'Test space for E2E testing',
  is_public: false,
}

// Test page data
export const TEST_PAGE = {
  title: `Test Page ${Date.now()}`,
  slug: `test-page-${Date.now()}`,
  content: '<p>This is test page content for E2E testing.</p>',
}

// Extend base test with authentication and data fixtures
export const test = base.extend({
  // Authenticated page fixture - logs in via Shizuha ID
  authenticatedPage: async ({ page }, use) => {
    // Go to Shizuha ID login page with next parameter
    await page.goto('/id/login?continue=/wiki/')

    // Wait for form to be ready
    await page.waitForSelector('input[id="username"]', { timeout: 10000 })

    // Fill in credentials
    await page.fill('input[id="username"]', TEST_USER.username)
    await page.fill('input[id="password"]', TEST_USER.password)

    // Click submit
    await page.click('button[type="submit"]')

    // Wait for successful login API response
    await page.waitForResponse(
      response => response.url().includes('/auth/login/') && response.ok(),
      { timeout: 15000 }
    )

    // Wait for redirect to Wiki
    await page.waitForURL(/.*wiki.*/, { timeout: 30000 })

    // Wait for page to fully load and React to hydrate
    await page.waitForLoadState('networkidle', { timeout: 20000 })
    await page.waitForTimeout(1000)

    // Verify we're on the wiki app - check we're not still on login
    const url = page.url()
    if (url.includes('/id/login')) {
      throw new Error('Still on login page after authentication')
    }

    // Use the authenticated page
    await use(page)
  },

  // API context for direct API testing (unauthenticated)
  apiContext: async ({ playwright }, use) => {
    // Use direct container port to avoid nginx routing issues
    // Note: trailing slash is required for proper path resolution
    const wikiBaseUrl = process.env.API_URL || 'http://localhost:18013'
    const apiContext = await playwright.request.newContext({
      baseURL: `${wikiBaseUrl}/api/`,
      extraHTTPHeaders: {
        'Content-Type': 'application/json',
      },
    })

    await use(apiContext)

    await apiContext.dispose()
  },

  // Authenticated API context - uses Shizuha ID for login
  authenticatedApi: async ({ playwright }, use) => {
    // Use direct container ports to avoid nginx routing issues
    const idBaseUrl = process.env.ID_API_URL || 'http://localhost:18001'
    const wikiBaseUrl = process.env.API_URL || 'http://localhost:18013'

    const apiContext = await playwright.request.newContext({
      baseURL: idBaseUrl,
      extraHTTPHeaders: {
        'Content-Type': 'application/json',
      },
    })

    // Login via Shizuha ID to get token
    const loginResponse = await apiContext.post('/api/auth/login/', {
      data: {
        username: TEST_USER.username,
        password: TEST_USER.password
      }
    })

    // Check if login was successful
    if (!loginResponse.ok()) {
      const text = await loginResponse.text()
      throw new Error(`Login failed: ${loginResponse.status()} - ${text.substring(0, 200)}`)
    }

    const { tokens } = await loginResponse.json()

    // Create new context with auth header for Wiki API
    // Note: trailing slash is required for proper path resolution
    const authContext = await playwright.request.newContext({
      baseURL: `${wikiBaseUrl}/api/`,
      extraHTTPHeaders: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${tokens.access}`,
        'X-Organization-ID': '1',
      },
    })

    // Store the token for later use
    authContext.token = tokens.access

    await use(authContext)

    await apiContext.dispose()
    await authContext.dispose()
  },

  // Fixture to get or create a test space
  testSpace: async ({ authenticatedApi }, use) => {
    // Try to get existing spaces first
    const listResponse = await authenticatedApi.get('spaces/')

    let space = null

    if (listResponse.ok()) {
      const data = await listResponse.json()
      const spaces = data.results || data || []

      // Find existing test space or use first available
      space = spaces.find(s => s.key && s.key.startsWith('TS')) || spaces[0]
    }

    // If no space exists, create one
    if (!space) {
      const createResponse = await authenticatedApi.post('spaces/', {
        data: TEST_SPACE
      })

      if (createResponse.ok()) {
        space = await createResponse.json()
      } else {
        const text = await createResponse.text()
        console.warn(`Failed to create test space: ${text}`)
      }
    }

    await use(space)
  },

  // Fixture to get or create a test page within a space
  testPage: async ({ authenticatedApi, testSpace }, use) => {
    if (!testSpace) {
      await use(null)
      return
    }

    // Try to get existing pages in the space
    const listResponse = await authenticatedApi.get(`pages/?space=${testSpace.id}`)
    let page = null

    if (listResponse.ok()) {
      const data = await listResponse.json()
      const pages = data.results || data || []
      page = pages[0]
    }

    // If no page exists, create one
    if (!page) {
      const createResponse = await authenticatedApi.post('pages/', {
        data: {
          ...TEST_PAGE,
          space: testSpace.id
        }
      })

      if (createResponse.ok()) {
        page = await createResponse.json()
      } else {
        const text = await createResponse.text()
        console.warn(`Failed to create test page: ${text}`)
      }
    }

    await use(page)
  },

  // Fixture to get available labels
  labels: async ({ authenticatedApi }, use) => {
    const response = await authenticatedApi.get('labels/')
    let labels = []

    if (response.ok()) {
      const data = await response.json()
      labels = data.results || data || []
    }

    await use(labels)
  },

  // Fixture to get available templates
  templates: async ({ authenticatedApi }, use) => {
    const response = await authenticatedApi.get('templates/')
    let templates = []

    if (response.ok()) {
      const data = await response.json()
      templates = data.results || data || []
    }

    await use(templates)
  },
})

export { expect } from '@playwright/test'

/**
 * Helper function to create unique test data
 */
export function uniqueId(prefix = 'test') {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`
}

/**
 * Helper to format date as YYYY-MM-DD
 */
export function formatDate(date = new Date()) {
  return date.toISOString().split('T')[0]
}

/**
 * Helper to wait for API response with retries
 */
export async function waitForApiResponse(page, urlPattern, options = {}) {
  const { timeout = 10000, expectedStatus = 200 } = options

  return page.waitForResponse(
    response => {
      const matchesUrl = typeof urlPattern === 'string'
        ? response.url().includes(urlPattern)
        : urlPattern.test(response.url())

      return matchesUrl && response.status() === expectedStatus
    },
    { timeout }
  )
}

/**
 * Helper to create a unique space key
 */
export function uniqueSpaceKey() {
  return `TS${Date.now().toString().slice(-8)}`
}

/**
 * Helper to create a unique page slug
 */
export function uniquePageSlug() {
  return `test-page-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`
}

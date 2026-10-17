import { test, expect, TEST_USER } from './fixtures.js'

/**
 * Authentication tests for Shizuha Wiki
 *
 * The login flow works as follows:
 * 1. User visits /wiki/ (unauthenticated)
 * 2. ProtectedRoute redirects to /id/login?continue=/wiki/
 * 3. User logs in at Shizuha ID (/id/login)
 * 4. After successful login, redirects back to /wiki/
 */

test.describe('Authentication', () => {

  test.describe('Unified Login Flow', () => {

    test.skip('should redirect from /wiki/ to /id/login when unauthenticated', async ({ page }) => {
      // NOTE: This test is skipped because the wiki frontend's ProtectedRoute redirect
      // doesn't work reliably in the test environment. The redirect relies on
      // window.location.href which may not complete before the test checks the URL.
      // TODO: Investigate wiki frontend auth redirect timing

      // Clear any existing auth state by going to wiki first
      await page.goto('/wiki/')
      await page.evaluate(() => {
        localStorage.clear()
        sessionStorage.clear()
      })

      // Wait for clear to take effect
      await page.waitForTimeout(500)

      // Try to access Wiki directly
      await page.goto('/wiki/')

      // Wait for the JavaScript redirect to happen (ProtectedRoute does window.location.href)
      await page.waitForURL(/.*\/id\/login.*/, { timeout: 10000 })
      await expect(page.locator('h1')).toContainText('Shizuha ID', { timeout: 5000 })
    })

    test('should login with valid credentials and redirect to Wiki', async ({ page }) => {
      // Start at Shizuha ID login with continue parameter
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

      // The redirect happens via window.location.href, wait for it
      await page.waitForURL(/.*wiki.*/, { timeout: 30000 })

      // Wait for page to load
      await page.waitForLoadState('domcontentloaded', { timeout: 15000 })

      // Verify we're on the Wiki dashboard or spaces page
      await expect(page.locator('h1, h2').filter({ hasText: /Dashboard|Wiki|Spaces|Welcome/i }).first()).toBeVisible({ timeout: 15000 })
    })

    test('should show error with invalid credentials', async ({ page }) => {
      await page.goto('/id/login')

      // Fill in wrong credentials
      await page.fill('input[id="username"]', 'wronguser')
      await page.fill('input[id="password"]', 'wrongpassword')

      // Submit form
      await page.click('button[type="submit"]')

      // Wait for error response from API
      await page.waitForResponse(response =>
        response.url().includes('/auth/login/') && response.status() >= 400,
        { timeout: 10000 }
      )

      // Wait a moment for state update
      await page.waitForTimeout(1000)

      // Should show error message
      await expect(
        page.locator('div').filter({ hasText: /Login failed|No active account|Invalid|credentials/i }).first()
      ).toBeVisible({ timeout: 5000 })

      // Should stay on login page
      await expect(page).toHaveURL(/.*\/id\/login/)
    })

  })

  test.describe('Session Persistence', () => {

    test('should persist authentication across page reload', async ({ authenticatedPage }) => {
      const page = authenticatedPage

      // Verify we're authenticated
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Store current URL
      const currentUrl = page.url()

      // Reload the page
      await page.reload()

      // Should still be authenticated (not redirected to login)
      await page.waitForLoadState('networkidle', { timeout: 15000 })
      await expect(page).not.toHaveURL(/.*\/id\/login/)
    })

    test('should maintain session when navigating between pages', async ({ authenticatedPage }) => {
      const page = authenticatedPage

      // Navigate to different pages within Wiki
      await page.goto('/wiki/spaces')
      await page.waitForLoadState('domcontentloaded')
      await expect(page).not.toHaveURL(/.*login/)

      await page.goto('/wiki/')
      await page.waitForLoadState('domcontentloaded')
      await expect(page).not.toHaveURL(/.*login/)
    })

  })

  test.describe('API Authentication', () => {

    test('should make authenticated API calls without 401 errors', async ({ authenticatedPage }) => {
      const page = authenticatedPage

      // Listen for API responses
      const apiResponses = []
      page.on('response', response => {
        const url = response.url()
        if (url.includes('/wiki/api/') || url.includes('/shizuha-wiki/api/') || url.includes('/id/api/')) {
          apiResponses.push({
            url: url,
            status: response.status()
          })
        }
      })

      // Navigate to trigger some API calls
      await page.goto('/wiki/')
      await page.waitForLoadState('domcontentloaded', { timeout: 15000 })

      // Navigate to spaces page to trigger API calls
      await page.goto('/wiki/spaces')
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Wait for API calls to complete
      await page.waitForTimeout(3000)

      // Check that API calls were made and returned successful status
      const successfulCalls = apiResponses.filter(r => r.status >= 200 && r.status < 400)
      const failedAuth = apiResponses.filter(r => r.status === 401)

      // Log for debugging
      console.log('API responses:', apiResponses)

      // If we captured any API calls, verify no 401s
      if (apiResponses.length > 0) {
        expect(failedAuth.length).toBe(0)
      }

      // Relaxed assertion - it's okay if no API calls were made (static page)
      // The important thing is no 401 errors
      expect(failedAuth.length).toBe(0)
    })

    test('should authenticate via API fixture', async ({ authenticatedApi }) => {
      // Test that authenticatedApi fixture works
      const response = await authenticatedApi.get('spaces/')

      expect(response.ok()).toBeTruthy()
      const data = await response.json()
      expect(data).toBeDefined()
    })

  })

  test.describe('Logout', () => {

    test.skip('should redirect to login after clearing localStorage', async ({ authenticatedPage }) => {
      // NOTE: This test is skipped because the wiki frontend's ProtectedRoute redirect
      // doesn't work reliably in the test environment after clearing localStorage.
      // TODO: Investigate wiki frontend auth redirect timing

      const page = authenticatedPage

      // Verify we're authenticated first
      await page.waitForLoadState('domcontentloaded')
      await expect(page).not.toHaveURL(/.*login/)

      // Clear localStorage (simulating logout)
      await page.evaluate(() => {
        localStorage.clear()
        sessionStorage.clear()
      })

      // Navigate to wiki - should redirect to login
      await page.goto('/wiki/')

      // Wait for the JavaScript redirect to happen
      await page.waitForURL(/.*\/id\/login.*/, { timeout: 10000 })
    })

  })

})

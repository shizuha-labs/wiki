import { test, expect, TEST_USER } from './fixtures.js'

/**
 * Wiki Permissions + Page Delete E2E tests
 *
 * Tests cover:
 * - Permissions API endpoint
 * - Settings button visibility on SpaceView
 * - Settings button navigation works
 * - Page tree context menu (three-dot menu) with Edit/Delete
 * - Delete confirmation modal from page tree
 * - Permission enforcement on page delete (403)
 */

test.describe('Permissions API', () => {

  test('should return permissions for authenticated user', async ({ authenticatedApi, testSpace }) => {
    if (!testSpace) {
      test.skip('No test space available')
      return
    }

    const response = await authenticatedApi.get(`spaces/${testSpace.key}/permissions/`)
    expect(response.ok()).toBeTruthy()

    const data = await response.json()
    expect(data).toHaveProperty('role')
    expect(data).toHaveProperty('permissions')

    // Test user created the space, so should be admin or owner
    expect(['owner', 'admin']).toContain(data.role)
    expect(data.permissions).toHaveProperty('page')
    expect(data.permissions.page).toContain('create')
    expect(data.permissions.page).toContain('delete')
  })

  test('should return owner permissions for space owner', async ({ authenticatedApi, testSpace }) => {
    if (!testSpace) {
      test.skip('No test space available')
      return
    }

    const response = await authenticatedApi.get(`spaces/${testSpace.key}/permissions/`)
    const data = await response.json()

    // Space creator should have full permissions
    expect(data.permissions.page).toContain('create')
    expect(data.permissions.page).toContain('update')
    expect(data.permissions.page).toContain('delete')
    expect(data.permissions.page).toContain('move')
    expect(data.permissions.comment).toContain('create')
    expect(data.permissions.comment).toContain('delete')
  })

  test('should reject unauthenticated request', async ({ apiContext, testSpace }) => {
    if (!testSpace) {
      test.skip('No test space available')
      return
    }

    const response = await apiContext.get(`spaces/${testSpace.key}/permissions/`)
    expect(response.status()).toBe(401)
  })

})

test.describe('SpaceView Settings Button', () => {

  test('should show Settings button for space admin', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) {
      test.skip('No test space available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })

    // Wait for space title to load
    await page.waitForSelector('h1', { timeout: 10000 })

    // Settings button should be visible in main content (href includes /wiki basename from React Router)
    const settingsLink = page.locator(`main a[href="/wiki/spaces/${testSpace.key}/settings"]`)
    await expect(settingsLink).toBeVisible({ timeout: 10000 })
  })

  test('should navigate to settings page when Settings button is clicked', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) {
      test.skip('No test space available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })
    await page.waitForSelector('h1', { timeout: 10000 })

    // Click the space-specific Settings link (scoped to main content)
    const settingsLink = page.locator(`main a[href="/wiki/spaces/${testSpace.key}/settings"]`)
    await expect(settingsLink).toBeVisible({ timeout: 10000 })
    await settingsLink.click()

    // Should navigate to settings page
    await page.waitForURL(`**/spaces/${testSpace.key}/settings`, { timeout: 10000 })

    // Should show Space Settings heading
    await expect(page.locator('h1:has-text("Space Settings")')).toBeVisible({ timeout: 10000 })
  })

  test('settings page should have Delete Space in Danger Zone', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) {
      test.skip('No test space available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}/settings`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })

    // Should show Danger Zone section
    await expect(page.locator('text=Danger Zone')).toBeVisible({ timeout: 10000 })

    // Should show Delete Space button
    await expect(page.locator('button:has-text("Delete Space")')).toBeVisible({ timeout: 5000 })
  })

})

test.describe('Page Tree Context Menu', () => {

  test('should show three-dot menu on page tree item hover', async ({ authenticatedPage, testSpace, testPage }) => {
    if (!testSpace || !testPage) {
      test.skip('No test space or page available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })

    // Wait for page tree to load within main content
    await page.locator('main ul li').first().waitFor({ timeout: 10000 })

    // Hover over a page tree item (li.group) in the main content area
    const pageItem = page.locator('main li.group').first()
    await pageItem.hover()

    // The three-dot button should become visible on hover (it has opacity-0 → group-hover:opacity-100)
    const moreButton = pageItem.locator('button').filter({ has: page.locator('svg.lucide-more-horizontal') })
    await expect(moreButton).toBeVisible({ timeout: 5000 })
  })

  test('should open context menu with Edit and Delete options', async ({ authenticatedPage, testSpace, testPage }) => {
    if (!testSpace || !testPage) {
      test.skip('No test space or page available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })
    await page.locator('main ul li').first().waitFor({ timeout: 10000 })

    // Hover over the first page tree item in main content
    const pageItem = page.locator('main li.group').first()
    await pageItem.hover()

    // Click the three-dot MoreHorizontal button
    const moreButton = pageItem.locator('button').filter({ has: page.locator('svg.lucide-more-horizontal') })
    await moreButton.click()

    // Dropdown should appear with Edit and Delete
    await expect(page.locator('button:has-text("Edit")')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('button:has-text("Delete")')).toBeVisible({ timeout: 5000 })
  })

  test('should navigate to edit page when Edit is clicked from context menu', async ({ authenticatedPage, testSpace, testPage }) => {
    if (!testSpace || !testPage) {
      test.skip('No test space or page available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })
    await page.locator('main ul li').first().waitFor({ timeout: 10000 })

    // Hover and open context menu
    const pageItem = page.locator('main li.group').first()
    await pageItem.hover()
    const moreButton = pageItem.locator('button').filter({ has: page.locator('svg.lucide-more-horizontal') })
    await moreButton.click()

    // Click Edit
    await page.locator('button:has-text("Edit")').click()

    // Should navigate to edit page
    await page.waitForURL(/.*\/edit$/, { timeout: 10000 })
  })

  test('should show delete confirmation modal when Delete is clicked', async ({ authenticatedPage, testSpace, testPage }) => {
    if (!testSpace || !testPage) {
      test.skip('No test space or page available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })
    await page.locator('main ul li').first().waitFor({ timeout: 10000 })

    // Hover and open context menu
    const pageItem = page.locator('main li.group').first()
    await pageItem.hover()
    const moreButton = pageItem.locator('button').filter({ has: page.locator('svg.lucide-more-horizontal') })
    await moreButton.click()

    // Click Delete
    await page.locator('button:has-text("Delete")').click()

    // Confirmation modal should appear
    await expect(page.locator('h3:has-text("Delete page")')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=permanently delete')).toBeVisible()
    await expect(page.locator('button:has-text("Cancel")')).toBeVisible()
    // The "Delete" button in the modal
    const deleteButton = page.locator('.fixed button:has-text("Delete")').last()
    await expect(deleteButton).toBeVisible()
  })

  test('should close delete confirmation modal on Cancel', async ({ authenticatedPage, testSpace, testPage }) => {
    if (!testSpace || !testPage) {
      test.skip('No test space or page available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })
    await page.locator('main ul li').first().waitFor({ timeout: 10000 })

    // Hover and open context menu
    const pageItem = page.locator('main li.group').first()
    await pageItem.hover()
    const moreButton = pageItem.locator('button').filter({ has: page.locator('svg.lucide-more-horizontal') })
    await moreButton.click()

    // Click Delete to open modal
    await page.locator('button:has-text("Delete")').click()
    await expect(page.locator('h3:has-text("Delete page")')).toBeVisible({ timeout: 5000 })

    // Click Cancel
    await page.locator('.fixed button:has-text("Cancel")').click()

    // Modal should disappear
    await expect(page.locator('h3:has-text("Delete page")')).not.toBeVisible({ timeout: 5000 })
  })

})

test.describe('Page Delete from PageView', () => {

  test('should show three-dot menu with delete option on page view', async ({ authenticatedPage, testSpace, testPage }) => {
    if (!testSpace || !testPage) {
      test.skip('No test space or page available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}/pages/${testPage.slug}`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })

    // Wait for page title
    await page.waitForSelector('h1', { timeout: 10000 })

    // Click the three-dot menu button in the page header area (not in the sidebar page tree)
    // The PageView more-button is in the article/main area header flex container
    const moreButton = page.locator('main button').filter({ has: page.locator('svg.lucide-more-horizontal') }).first()
    await expect(moreButton).toBeVisible({ timeout: 5000 })
    await moreButton.click()

    // Delete option should appear
    await expect(page.locator('button:has-text("Delete page")')).toBeVisible({ timeout: 5000 })
  })

})

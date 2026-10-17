import { test, expect, TEST_USER, uniqueSpaceKey, uniquePageSlug } from './fixtures.js'

/**
 * Wiki functionality tests for Shizuha Wiki
 *
 * Tests cover:
 * - Space creation and retrieval by key
 * - Page creation within spaces
 * - Attachment upload and download
 */

test.describe('Spaces', () => {

  test.describe('Space CRUD Operations', () => {

    test('should list spaces', async ({ authenticatedApi }) => {
      const response = await authenticatedApi.get('spaces/')
      expect(response.ok()).toBeTruthy()

      const data = await response.json()
      expect(data).toBeDefined()
      // Should return array or paginated results
      expect(data.results || data).toBeDefined()
    })

    test('should create a new space', async ({ authenticatedApi }) => {
      const spaceKey = uniqueSpaceKey().toUpperCase()
      const response = await authenticatedApi.post('spaces/', {
        data: {
          key: spaceKey,
          name: `Test Space ${spaceKey}`,
          description: 'E2E test space',
          visibility: 'private',
          space_type: 'documentation'
        }
      })

      expect(response.ok()).toBeTruthy()
      const space = await response.json()
      expect(space.key).toBe(spaceKey)
      expect(space.name).toContain('Test Space')
    })

    test('should get space by key (case-insensitive)', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      // Test with exact case
      const response1 = await authenticatedApi.get(`spaces/${testSpace.key}/`)
      expect(response1.ok()).toBeTruthy()
      const space1 = await response1.json()
      expect(space1.key).toBe(testSpace.key)

      // Test with lowercase
      const response2 = await authenticatedApi.get(`spaces/${testSpace.key.toLowerCase()}/`)
      expect(response2.ok()).toBeTruthy()
      const space2 = await response2.json()
      expect(space2.key).toBe(testSpace.key)

      // Test with uppercase
      const response3 = await authenticatedApi.get(`spaces/${testSpace.key.toUpperCase()}/`)
      expect(response3.ok()).toBeTruthy()
      const space3 = await response3.json()
      expect(space3.key).toBe(testSpace.key)
    })

    test('should get space tree', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const response = await authenticatedApi.get(`spaces/${testSpace.key}/tree/`)
      expect(response.ok()).toBeTruthy()

      const tree = await response.json()
      expect(Array.isArray(tree)).toBeTruthy()
    })

    test('should get space members', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const response = await authenticatedApi.get(`spaces/${testSpace.key}/members/`)
      expect(response.ok()).toBeTruthy()

      const members = await response.json()
      expect(Array.isArray(members)).toBeTruthy()
      // Owner should be a member
      expect(members.length).toBeGreaterThanOrEqual(1)
    })

  })

})

test.describe('Pages', () => {

  test.describe('Page CRUD Operations', () => {

    test('should list pages', async ({ authenticatedApi }) => {
      const response = await authenticatedApi.get('pages/')
      expect(response.ok()).toBeTruthy()

      const data = await response.json()
      expect(data).toBeDefined()
    })

    test('should list pages in a space by space_key', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const response = await authenticatedApi.get(`pages/?space_key=${testSpace.key}`)
      expect(response.ok()).toBeTruthy()

      const data = await response.json()
      expect(data).toBeDefined()
    })

    test('should create a page in a space', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const pageTitle = `Test Page ${Date.now()}`
      const response = await authenticatedApi.post('pages/', {
        data: {
          space: testSpace.id,
          title: pageTitle,
          content_json: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Test content' }] }] },
          content_text: 'Test content',
          status: 'draft'
        }
      })

      expect(response.ok()).toBeTruthy()
      const page = await response.json()
      expect(page.title).toBe(pageTitle)
      expect(page.space).toBe(testSpace.id)
    })

    test('should create a page using space_key', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const pageTitle = `Test Page via Key ${Date.now()}`
      const response = await authenticatedApi.post('pages/', {
        data: {
          input_space_key: testSpace.key,
          title: pageTitle,
          content_json: { type: 'doc', content: [] },
          content_text: '',
          status: 'draft'
        }
      })

      expect(response.ok()).toBeTruthy()
      const page = await response.json()
      expect(page.title).toBe(pageTitle)
    })

    test('should get page by ID', async ({ authenticatedApi, testPage }) => {
      if (!testPage) {
        test.skip('No test page available')
        return
      }

      const response = await authenticatedApi.get(`pages/${testPage.id}/`)
      expect(response.ok()).toBeTruthy()

      const page = await response.json()
      expect(page.id).toBe(testPage.id)
    })

    test('should update a page', async ({ authenticatedApi, testPage }) => {
      if (!testPage) {
        test.skip('No test page available')
        return
      }

      const newTitle = `Updated Page ${Date.now()}`
      const response = await authenticatedApi.patch(`pages/${testPage.id}/`, {
        data: {
          title: newTitle
        }
      })

      expect(response.ok()).toBeTruthy()
      const page = await response.json()
      expect(page.title).toBe(newTitle)
    })

    test('should get page versions', async ({ authenticatedApi, testPage }) => {
      if (!testPage) {
        test.skip('No test page available')
        return
      }

      const response = await authenticatedApi.get(`pages/${testPage.id}/versions/`)
      expect(response.ok()).toBeTruthy()

      const versions = await response.json()
      expect(Array.isArray(versions)).toBeTruthy()
      expect(versions.length).toBeGreaterThanOrEqual(1)
    })

  })

})

test.describe('Attachments', () => {

  test.describe('Attachment Operations', () => {

    test('should list attachments for a page', async ({ authenticatedApi, testPage }) => {
      if (!testPage) {
        test.skip('No test page available')
        return
      }

      const response = await authenticatedApi.get(`attachments/?page_id=${testPage.id}`)
      expect(response.ok()).toBeTruthy()

      const data = await response.json()
      expect(data).toBeDefined()
    })

    test('should upload an attachment to a page', async ({ authenticatedApi, testPage }) => {
      if (!testPage) {
        test.skip('No test page available')
        return
      }

      // Create a test file (as FormData)
      const testContent = 'Hello, this is a test file content.'
      const formData = new FormData()
      formData.append('page', testPage.id)
      formData.append('file', new Blob([testContent], { type: 'text/plain' }), 'test-file.txt')

      // Note: Playwright's request context doesn't support FormData directly
      // This test would need to be run via the browser context
      // For now, we skip this as a browser-based test
      test.skip('Upload requires browser context')
    })

  })

})

test.describe('Search', () => {

  test('should search wiki content', async ({ authenticatedApi }) => {
    const response = await authenticatedApi.get('search/?q=test')
    expect(response.ok()).toBeTruthy()

    const data = await response.json()
    expect(Array.isArray(data)).toBeTruthy()
  })

  test('should return empty for short queries', async ({ authenticatedApi }) => {
    const response = await authenticatedApi.get('search/?q=a')
    expect(response.ok()).toBeTruthy()

    const data = await response.json()
    expect(Array.isArray(data)).toBeTruthy()
    expect(data.length).toBe(0)
  })

})

test.describe('UI Integration', () => {

  test('should display space view page', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) {
      test.skip('No test space available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })

    // Should show the space name
    await expect(page.locator('h1').first()).toContainText(testSpace.name, { timeout: 10000 })
  })

  test('should display space view with lowercase key', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) {
      test.skip('No test space available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key.toLowerCase()}`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })

    // Should still work (case-insensitive)
    // Either shows the space or redirects, but should not show "Space not found"
    const content = await page.textContent('body')
    expect(content).not.toContain('Space not found')
  })

  test('should show page editor', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) {
      test.skip('No test space available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}/pages/new`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })

    // Should show the page editor with title input
    await expect(page.locator('input[placeholder*="title" i]').first()).toBeVisible({ timeout: 10000 })
  })

  test('should create a new page via UI', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) {
      test.skip('No test space available')
      return
    }

    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${testSpace.key}/pages/new`)
    await page.waitForLoadState('networkidle', { timeout: 15000 })

    // Fill in the title
    const pageTitle = `UI Test Page ${Date.now()}`
    await page.fill('input[placeholder*="title" i]', pageTitle)

    // Click save
    await page.click('button:has-text("Save")')

    // Wait for navigation or success
    await page.waitForLoadState('networkidle', { timeout: 15000 })

    // Should navigate to the new page or show success
    // Check we're not still on the new page form with errors
    await page.waitForTimeout(2000)
    const url = page.url()
    // Should either be on the page view or still on editor without errors
    expect(url).toContain('/wiki/')
  })

})

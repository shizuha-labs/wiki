import { test, expect } from './fixtures'
import fs from 'fs'

/**
 * E2E tests for uploading attachments on a NEW (unsaved) page.
 *
 * Regression test for: attachments uploaded to a brand-new page (before the
 * first manual save) would disappear after refresh because the auto-save
 * created the page but the editor didn't track the new page ID, so a
 * subsequent manual save would create a duplicate page.
 */

test.describe('New Page Attachment Persistence', () => {
  const testTextPath = '/tmp/test-attachment.txt'

  test.beforeAll(async () => {
    fs.writeFileSync(testTextPath, 'Attachment content for new page E2E test')
  })

  test('attachment persists after uploading to new page and refreshing', async ({
    authenticatedPage,
    testSpace,
  }) => {
    test.skip(!testSpace, 'Test space not available')

    const page = authenticatedPage
    const uniqueTitle = `Attachment Test ${Date.now()}`

    // 1. Navigate to create new page in the test space
    await page.goto(`/wiki/spaces/${testSpace.key}/new`)
    await page.waitForLoadState('networkidle')

    // 2. Enter a title (required before attachment auto-save can work)
    const titleInput = page.locator('input[placeholder="Page title"]')
    await titleInput.fill(uniqueTitle)

    // 3. Wait for editor to be ready
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // 4. Open the attachment panel via toolbar button
    const attachButton = page.locator('button[title="Attachments"]')
    await attachButton.click()

    // 5. Upload a file via the attachment panel's file input
    //    The panel has a dropzone with a hidden file input
    const fileInput = page.locator('input[type="file"]').last()
    await fileInput.setInputFiles(testTextPath)

    // 6. Wait for the auto-save toast ("Page saved as draft") and upload toast
    await page.waitForSelector('text=Page saved as draft', { timeout: 15000 })
    await page.waitForSelector('text=Uploaded test-attachment.txt', { timeout: 15000 })

    // 7. Verify the attachment is visible in the panel
    await expect(page.locator('text=test-attachment.txt')).toBeVisible({ timeout: 5000 })

    // 8. Get the current URL (should have been updated to the new page's edit URL)
    const editUrl = page.url()
    expect(editUrl).toMatch(/\/pages\/.*\/edit/)

    // 9. Navigate to the page view (remove /edit from URL)
    const viewUrl = editUrl.replace(/\/edit$/, '')
    await page.goto(viewUrl)
    await page.waitForLoadState('networkidle')

    // 10. Verify the page title matches
    await expect(page.locator(`text=${uniqueTitle}`).first()).toBeVisible({ timeout: 10000 })

    // 11. Expand attachments section and verify the file is listed
    const attachmentsButton = page.locator('button:has-text("Attachments")')
    if (await attachmentsButton.isVisible()) {
      await attachmentsButton.click()
    }
    await expect(page.locator('text=test-attachment.txt')).toBeVisible({ timeout: 10000 })

    // 12. Now refresh the page entirely
    await page.reload()
    await page.waitForLoadState('networkidle')

    // 13. Verify page title still shows
    await expect(page.locator(`text=${uniqueTitle}`).first()).toBeVisible({ timeout: 10000 })

    // 14. Open attachments again and verify the file persists after refresh
    const attachmentsButton2 = page.locator('button:has-text("Attachments")')
    if (await attachmentsButton2.isVisible()) {
      await attachmentsButton2.click()
    }
    await expect(page.locator('text=test-attachment.txt')).toBeVisible({ timeout: 10000 })
  })

  test('manual save after attachment upload does not create duplicate page', async ({
    authenticatedPage,
    authenticatedApi,
    testSpace,
  }) => {
    test.skip(!testSpace, 'Test space not available')

    const page = authenticatedPage
    const uniqueTitle = `Dedup Test ${Date.now()}`

    // 1. Create new page
    await page.goto(`/wiki/spaces/${testSpace.key}/new`)
    await page.waitForLoadState('networkidle')

    // 2. Enter title
    const titleInput = page.locator('input[placeholder="Page title"]')
    await titleInput.fill(uniqueTitle)

    // 3. Wait for editor
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // 4. Open attachment panel and upload
    const attachButton = page.locator('button[title="Attachments"]')
    await attachButton.click()

    const fileInput = page.locator('input[type="file"]').last()
    await fileInput.setInputFiles(testTextPath)

    // 5. Wait for auto-save
    await page.waitForSelector('text=Page saved as draft', { timeout: 15000 })
    await page.waitForSelector('text=Uploaded test-attachment.txt', { timeout: 15000 })

    // 6. Now click manual Save button
    const saveButton = page.locator('button:has-text("Save")')
    await saveButton.click()

    // 7. Wait for navigation to the page view
    await page.waitForURL(/\/pages\/.*[^/]$/, { timeout: 15000 })
    await page.waitForLoadState('networkidle')

    // 8. Query the API for pages with this exact title - should be exactly 1
    const searchResponse = await authenticatedApi.get(
      `pages/?space=${testSpace.id}&search=${encodeURIComponent(uniqueTitle)}`
    )
    expect(searchResponse.ok()).toBeTruthy()

    const data = await searchResponse.json()
    const pages = data.results || data || []
    const matchingPages = pages.filter(p => p.title === uniqueTitle)

    expect(matchingPages.length).toBe(1)
  })
})

import { test, expect } from './fixtures.js'
import fs from 'fs'

/**
 * E2E tests for Wiki Labels and Attachments
 *
 * Verifies the user-reported issue: "Label not create and document not attached"
 *
 * Tests label CRUD, label-page associations, attachment CRUD, UI uploads,
 * and the auto-save + upload flow on new pages.
 */

// Helper: login and get JWT token for direct fetch calls
async function getAuthToken() {
  const loginResp = await fetch('http://shizuha-id:8001/api/auth/login/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'testuser', password: 'TestPass123' }),
  })
  const { tokens } = await loginResp.json()
  return tokens.access
}

// Helper: upload attachment via direct fetch (avoids Playwright Content-Type conflict)
async function uploadAttachment(token, pageId, filename, content, mimeType = 'text/plain') {
  const formData = new FormData()
  formData.append('page', pageId)
  formData.append('file', new Blob([content], { type: mimeType }), filename)
  return fetch('http://shizuha-wiki:8013/api/attachments/', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'X-Organization-ID': '1' },
    body: formData,
  })
}

// ============================================================================
// LABELS
// ============================================================================

test.describe('Labels', () => {

  test.describe('Label CRUD via API', () => {

    test('should create a new label', async ({ authenticatedApi }) => {
      const labelName = `e2e-label-${Date.now()}`
      const response = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#3b82f6' }
      })

      expect(response.ok()).toBeTruthy()
      const label = await response.json()
      expect(label.name).toBe(labelName)
      expect(label.color).toBe('#3b82f6')
      expect(label.id).toBeDefined()
      expect(label.pages_count).toBe(0)
    })

    test('should list labels including newly created one', async ({ authenticatedApi }) => {
      const labelName = `e2e-list-${Date.now()}`
      const createResp = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#ef4444' }
      })
      expect(createResp.ok()).toBeTruthy()
      const created = await createResp.json()

      // Fetch by ID to confirm it exists
      const getResp = await authenticatedApi.get(`labels/${created.id}/`)
      expect(getResp.ok()).toBeTruthy()
      const fetched = await getResp.json()
      expect(fetched.name).toBe(labelName)

      // List should include it (use search param if available, or check all pages)
      const listResp = await authenticatedApi.get(`labels/?search=${labelName}`)
      expect(listResp.ok()).toBeTruthy()
      const data = await listResp.json()
      const labels = data.results || data
      expect(Array.isArray(labels)).toBeTruthy()
      expect(labels.length).toBeGreaterThanOrEqual(1)
    })

    test('should reject duplicate label names with 400', async ({ authenticatedApi }) => {
      const labelName = `e2e-dup-${Date.now()}`

      const resp1 = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#3b82f6' }
      })
      expect(resp1.ok()).toBeTruthy()

      const resp2 = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#ef4444' }
      })
      expect(resp2.ok()).toBeFalsy()
      expect(resp2.status()).toBe(400)
    })

    test('should update a label', async ({ authenticatedApi }) => {
      const labelName = `e2e-update-${Date.now()}`
      const createResp = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#3b82f6' }
      })
      const label = await createResp.json()

      const updateResp = await authenticatedApi.patch(`labels/${label.id}/`, {
        data: { color: '#ef4444', description: 'Updated description' }
      })
      expect(updateResp.ok()).toBeTruthy()
      const updated = await updateResp.json()
      expect(updated.color).toBe('#ef4444')
      expect(updated.description).toBe('Updated description')
    })

    test('should delete a label', async ({ authenticatedApi }) => {
      const labelName = `e2e-delete-${Date.now()}`
      const createResp = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#3b82f6' }
      })
      const label = await createResp.json()

      const deleteResp = await authenticatedApi.delete(`labels/${label.id}/`)
      expect(deleteResp.ok()).toBeTruthy()

      const getResp = await authenticatedApi.get(`labels/${label.id}/`)
      expect(getResp.status()).toBe(404)
    })

  })

  test.describe('Labels on Pages via API', () => {

    test('PageCreateSerializer should return id and slug', async ({ authenticatedApi, testSpace }) => {
      test.skip(!testSpace, 'No test space available')

      const pageResp = await authenticatedApi.post('pages/', {
        data: {
          space: testSpace.id,
          title: `Serializer Test ${Date.now()}`,
          content_json: { type: 'doc', content: [] },
          content_text: '',
          status: 'draft',
        }
      })
      expect(pageResp.ok()).toBeTruthy()
      const page = await pageResp.json()

      expect(page.id).toBeDefined()
      expect(page.slug).toBeDefined()
    })

    test('should create page with labels and verify via list', async ({ authenticatedApi, testSpace }) => {
      test.skip(!testSpace, 'No test space available')

      // Create a label
      const labelName = `e2e-page-label-${Date.now()}`
      const labelResp = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#22c55e' }
      })
      expect(labelResp.ok()).toBeTruthy()
      const label = await labelResp.json()

      // Create page with that label
      const pageTitle = `Labeled Page ${Date.now()}`
      const pageResp = await authenticatedApi.post('pages/', {
        data: {
          space: testSpace.id,
          title: pageTitle,
          content_json: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Page with label' }] }] },
          content_text: 'Page with label',
          status: 'draft',
          label_ids: [label.id],
        }
      })
      expect(pageResp.ok()).toBeTruthy()
      const createdPage = await pageResp.json()
      expect(createdPage.id).toBeDefined()

      // Verify labels via detail endpoint
      const detailResp = await authenticatedApi.get(`pages/${createdPage.id}/`)
      expect(detailResp.ok()).toBeTruthy()
      const detail = await detailResp.json()

      expect(detail.labels).toBeDefined()
      expect(Array.isArray(detail.labels)).toBeTruthy()
      expect(detail.labels.some(l => l.id === label.id)).toBeTruthy()
    })

    test('should add labels to existing page via PATCH', async ({ authenticatedApi, testSpace }) => {
      test.skip(!testSpace, 'No test space available')

      // Create label
      const labelName = `e2e-patch-label-${Date.now()}`
      const labelResp = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#8b5cf6' }
      })
      const label = await labelResp.json()

      // Create page (BUG-1 fixed: create response now includes id)
      const pageTitle = `Unlabeled Page ${Date.now()}`
      const createResp = await authenticatedApi.post('pages/', {
        data: {
          space: testSpace.id,
          title: pageTitle,
          content_json: { type: 'doc', content: [] },
          content_text: '',
          status: 'draft',
        }
      })
      expect(createResp.ok()).toBeTruthy()
      const createdPage = await createResp.json()
      expect(createdPage.id).toBeDefined()

      // PATCH to add label
      const patchResp = await authenticatedApi.patch(`pages/${createdPage.id}/`, {
        data: { label_ids: [label.id] }
      })
      expect(patchResp.ok()).toBeTruthy()
      const patched = await patchResp.json()
      expect(patched.labels.some(l => l.id === label.id)).toBeTruthy()
    })

    test('should remove labels from page via PATCH', async ({ authenticatedApi, testSpace }) => {
      test.skip(!testSpace, 'No test space available')

      // Create label
      const labelName = `e2e-remove-label-${Date.now()}`
      const labelResp = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#ec4899' }
      })
      const label = await labelResp.json()

      // Create page with label (BUG-1 fixed: create response includes id)
      const pageTitle = `Remove Label Page ${Date.now()}`
      const createResp = await authenticatedApi.post('pages/', {
        data: {
          space: testSpace.id,
          title: pageTitle,
          content_json: { type: 'doc', content: [] },
          content_text: '',
          status: 'draft',
          label_ids: [label.id],
        }
      })
      expect(createResp.ok()).toBeTruthy()
      const createdPage = await createResp.json()
      expect(createdPage.id).toBeDefined()

      // Remove labels
      const patchResp = await authenticatedApi.patch(`pages/${createdPage.id}/`, {
        data: { label_ids: [] }
      })
      expect(patchResp.ok()).toBeTruthy()
      const patched = await patchResp.json()
      expect(patched.labels.length).toBe(0)
    })

    test('label pages_count should reflect assigned pages', async ({ authenticatedApi, testSpace }) => {
      test.skip(!testSpace, 'No test space available')

      const labelName = `e2e-count-${Date.now()}`
      const labelResp = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#06b6d4' }
      })
      const label = await labelResp.json()
      expect(label.pages_count).toBe(0)

      await authenticatedApi.post('pages/', {
        data: {
          space: testSpace.id,
          title: `Count Test Page ${Date.now()}`,
          content_json: { type: 'doc', content: [] },
          content_text: '',
          status: 'draft',
          label_ids: [label.id],
        }
      })

      const getResp = await authenticatedApi.get(`labels/${label.id}/`)
      const updatedLabel = await getResp.json()
      expect(updatedLabel.pages_count).toBe(1)
    })

  })

  test.describe('Label Creation via UI', () => {

    test('should create label from page editor and see it selected', async ({ authenticatedPage, testSpace }) => {
      test.skip(!testSpace, 'No test space available')

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/pages/new`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      const addLabelBtn = page.locator('button:has-text("Add label")')
      await expect(addLabelBtn).toBeVisible({ timeout: 10000 })
      await addLabelBtn.click()

      const labelInput = page.locator('input[placeholder="Label name"]')
      await expect(labelInput).toBeVisible({ timeout: 5000 })

      const labelName = `ui-label-${Date.now()}`
      await labelInput.fill(labelName)

      const labelCreatePromise = page.waitForResponse(
        response => response.url().includes('/labels/') && response.request().method() === 'POST',
        { timeout: 10000 }
      )

      await page.locator('button:has-text("Add")').last().click()

      const labelResponse = await labelCreatePromise
      expect(labelResponse.ok()).toBeTruthy()

      const labelData = await labelResponse.json()
      expect(labelData.name).toBe(labelName)

      await page.waitForTimeout(500)
      await expect(page.locator(`span:has-text("${labelName}")`).first()).toBeVisible({ timeout: 5000 })
    })

    test('should select existing label from dropdown', async ({ authenticatedPage, authenticatedApi, testSpace }) => {
      test.skip(!testSpace, 'No test space available')

      const labelName = `e2e-existing-${Date.now()}`
      const apiResp = await authenticatedApi.post('labels/', {
        data: { name: labelName, color: '#f97316' }
      })
      expect(apiResp.ok()).toBeTruthy()

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/pages/new`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      await page.locator('button:has-text("Add label")').click()
      await page.waitForTimeout(1000)
      const labelOption = page.locator(`button:has-text("${labelName}")`)
      await expect(labelOption).toBeVisible({ timeout: 5000 })
      await labelOption.click()

      await expect(page.locator(`span:has-text("${labelName}")`).first()).toBeVisible({ timeout: 5000 })
    })

    test('should persist labels when saving page', async ({ authenticatedPage, testSpace }) => {
      test.skip(!testSpace, 'No test space available')

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/pages/new`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      const pageTitle = `Label Persist Test ${Date.now()}`
      await page.fill('input[placeholder*="title" i]', pageTitle)

      // Create and select a label
      await page.locator('button:has-text("Add label")').click()
      const labelName = `persist-${Date.now()}`
      await page.locator('input[placeholder="Label name"]').fill(labelName)

      const labelCreatePromise = page.waitForResponse(
        response => response.url().includes('/labels/') && response.request().method() === 'POST',
        { timeout: 10000 }
      )
      await page.locator('button:has-text("Add")').last().click()
      await labelCreatePromise
      await page.waitForTimeout(500)

      // Close label dropdown (full-screen overlay covers the page)
      await page.locator('.fixed.inset-0.z-40').click({ force: true })
      await page.waitForTimeout(500)

      // Save the page
      const savePromise = page.waitForResponse(
        response => response.url().includes('/pages/') && response.request().method() === 'POST',
        { timeout: 15000 }
      )
      await page.click('button:has-text("Save")', { timeout: 10000 })
      const saveResp = await savePromise
      expect(saveResp.ok()).toBeTruthy()

      const savedPage = await saveResp.json()
      expect(savedPage.labels).toBeDefined()
      expect(savedPage.labels.some(l => l.name === labelName)).toBeTruthy()
    })

  })

})


// ============================================================================
// ATTACHMENTS
// ============================================================================

test.describe('Attachments', () => {

  const tmpTextFile = '/tmp/e2e-wiki-test.txt'
  const tmpImageFile = '/tmp/e2e-wiki-test.png'

  test.beforeAll(async () => {
    fs.writeFileSync(tmpTextFile, 'E2E attachment test content for wiki')

    // Minimal 1x1 PNG
    const pngData = Buffer.from([
      0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
      0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
      0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, 0xDE, 0x00, 0x00, 0x00,
      0x0C, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
      0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x05, 0xFE, 0xD4, 0xF6, 0x00, 0x00,
      0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82
    ])
    fs.writeFileSync(tmpImageFile, pngData)
  })

  // Note: Attachment API tests use direct fetch() because the Playwright
  // authenticatedApi fixture sets Content-Type: application/json in extraHTTPHeaders,
  // which overrides multipart/form-data needed for file uploads.

  test.describe('Attachment CRUD via API', () => {

    test('should upload a text file to existing page', async ({ testPage }) => {
      test.skip(!testPage, 'No test page available')

      const token = await getAuthToken()
      const response = await uploadAttachment(token, testPage.id, 'api-test.txt', 'API upload test content')

      expect(response.ok).toBeTruthy()
      const attachment = await response.json()
      expect(attachment.filename).toBe('api-test.txt')
      expect(attachment.mime_type).toBe('text/plain')
      expect(attachment.page).toBe(testPage.id)
      expect(attachment.file_size).toBeGreaterThan(0)
    })

    test('should upload a PNG image to existing page', async ({ testPage }) => {
      test.skip(!testPage, 'No test page available')

      const token = await getAuthToken()
      const pngData = fs.readFileSync(tmpImageFile)

      const formData = new FormData()
      formData.append('page', testPage.id)
      formData.append('file', new Blob([pngData], { type: 'image/png' }), 'api-test.png')

      const response = await fetch('http://shizuha-wiki:8013/api/attachments/', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'X-Organization-ID': '1' },
        body: formData,
      })

      expect(response.ok).toBeTruthy()
      const attachment = await response.json()
      expect(attachment.filename).toBe('api-test.png')
      expect(attachment.mime_type).toBe('image/png')
    })

    test('should list attachments after upload', async ({ testPage }) => {
      test.skip(!testPage, 'No test page available')

      const token = await getAuthToken()
      const uniqueName = `list-test-${Date.now()}.txt`
      await uploadAttachment(token, testPage.id, uniqueName, 'List test')

      const listResp = await fetch(
        `http://shizuha-wiki:8013/api/attachments/?page_id=${testPage.id}`,
        { headers: { Authorization: `Bearer ${token}`, 'X-Organization-ID': '1' } }
      )
      expect(listResp.ok).toBeTruthy()

      const data = await listResp.json()
      const attachments = data.results || data
      expect(Array.isArray(attachments)).toBeTruthy()
      expect(attachments.length).toBeGreaterThanOrEqual(1)
      expect(attachments.some(a => a.filename === uniqueName)).toBeTruthy()
    })

    test('should download an uploaded attachment', async ({ testPage }) => {
      test.skip(!testPage, 'No test page available')

      const token = await getAuthToken()
      const content = 'Download test content'
      const resp = await uploadAttachment(token, testPage.id, 'download-test.txt', content)
      const attachment = await resp.json()

      const downloadResp = await fetch(
        `http://shizuha-wiki:8013/api/attachments/${attachment.id}/download/`,
        { headers: { Authorization: `Bearer ${token}`, 'X-Organization-ID': '1' } }
      )
      expect(downloadResp.ok).toBeTruthy()

      const body = await downloadResp.text()
      expect(body).toContain(content)
    })

    test('should delete an attachment', async ({ testPage }) => {
      test.skip(!testPage, 'No test page available')

      const token = await getAuthToken()
      const resp = await uploadAttachment(token, testPage.id, 'delete-test.txt', 'To be deleted')
      const attachment = await resp.json()

      const deleteResp = await fetch(
        `http://shizuha-wiki:8013/api/attachments/${attachment.id}/`,
        { method: 'DELETE', headers: { Authorization: `Bearer ${token}`, 'X-Organization-ID': '1' } }
      )
      expect(deleteResp.ok).toBeTruthy()

      const getResp = await fetch(
        `http://shizuha-wiki:8013/api/attachments/${attachment.id}/`,
        { headers: { Authorization: `Bearer ${token}`, 'X-Organization-ID': '1' } }
      )
      expect(getResp.status).toBe(404)
    })

    test('should reject upload without page field', async () => {
      const token = await getAuthToken()
      const formData = new FormData()
      formData.append('file', new Blob(['No page'], { type: 'text/plain' }), 'orphan.txt')

      const response = await fetch('http://shizuha-wiki:8013/api/attachments/', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'X-Organization-ID': '1' },
        body: formData,
      })
      expect(response.ok).toBeFalsy()
    })

  })

  test.describe('Attachment Upload via UI on Existing Page', () => {

    test('should upload file via attachment panel on existing page', async ({ authenticatedPage, testSpace, testPage }) => {
      test.skip(!testSpace || !testPage, 'Test space or page not available')

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/pages/${testPage.slug}/edit`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Open attachment panel
      const attachBtn = page.locator('button[title="Attachments"]')
      await expect(attachBtn).toBeVisible({ timeout: 10000 })
      await attachBtn.click()
      await expect(page.locator('text=Click to upload')).toBeVisible({ timeout: 5000 })

      // Upload file
      const fileChooserPromise = page.waitForEvent('filechooser')
      await page.locator('text=Click to upload').click()
      const fileChooser = await fileChooserPromise

      const uploadPromise = page.waitForResponse(
        response => response.url().includes('/attachments/') && response.request().method() === 'POST',
        { timeout: 15000 }
      )
      await fileChooser.setFiles(tmpTextFile)

      const uploadResponse = await uploadPromise
      expect(uploadResponse.ok()).toBeTruthy()

      const uploadData = await uploadResponse.json()
      expect(uploadData.filename).toBe('e2e-wiki-test.txt')
      expect(uploadData.page).toBe(testPage.id)

      await expect(page.locator('text=e2e-wiki-test.txt').first()).toBeVisible({ timeout: 5000 })
    })

  })

  test.describe('Attachment Upload on NEW Page (Auto-Save Flow)', () => {

    test('should auto-save page and upload attachment on new page', async ({ authenticatedPage, testSpace }) => {
      test.skip(!testSpace, 'No test space available')

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/pages/new`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Enter title (required for auto-save)
      const pageTitle = `Auto-Save Attach Test ${Date.now()}`
      await page.fill('input[placeholder*="title" i]', pageTitle)

      // Open attachment panel
      const attachBtn = page.locator('button[title="Attachments"]')
      await expect(attachBtn).toBeVisible({ timeout: 10000 })
      await attachBtn.click()
      await expect(page.locator('text=Click to upload')).toBeVisible({ timeout: 5000 })

      // Upload a file — should trigger auto-save then attachment upload
      const fileChooserPromise = page.waitForEvent('filechooser')
      await page.locator('text=Click to upload').click()
      const fileChooser = await fileChooserPromise

      // Listen for page auto-save
      const pageCreatePromise = page.waitForResponse(
        response => response.url().includes('/pages/') && response.request().method() === 'POST',
        { timeout: 15000 }
      )

      await fileChooser.setFiles(tmpTextFile)

      // Verify page auto-save happens
      const pageCreateResponse = await pageCreatePromise
      expect(pageCreateResponse.ok()).toBeTruthy()

      const createdPage = await pageCreateResponse.json()

      expect(createdPage.id).toBeDefined()

      // Attachment upload must fire after auto-save with the new page ID
      let attachmentUploaded = false
      try {
        const uploadResponse = await page.waitForResponse(
          response => response.url().includes('/attachments/') && response.request().method() === 'POST',
          { timeout: 10000 }
        )
        if (uploadResponse.ok()) {
          const uploadData = await uploadResponse.json()
          expect(uploadData.filename).toBe('e2e-wiki-test.txt')
          attachmentUploaded = true
        }
      } catch {
        // Attachment upload never fired — this is the bug
      }

      expect(attachmentUploaded).toBeTruthy()
    })

    test('should show warning when trying to upload without title on new page', async ({ authenticatedPage, testSpace }) => {
      test.skip(!testSpace, 'No test space available')

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/pages/new`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Open attachment panel without entering a title
      const attachBtn = page.locator('button[title="Attachments"]')
      await expect(attachBtn).toBeVisible({ timeout: 10000 })
      await attachBtn.click()

      const fileChooserPromise = page.waitForEvent('filechooser')
      await page.locator('text=Click to upload').click()
      const fileChooser = await fileChooserPromise
      await fileChooser.setFiles(tmpTextFile)

      // Should see warning about needing a title
      await expect(
        page.locator('text=Please enter a page title').or(page.locator('text=Save the page first'))
      ).toBeVisible({ timeout: 5000 })
    })

  })

  test.describe('Attachment Panel State', () => {

    test('should show attachment count after upload on existing page', async ({ authenticatedPage, testSpace, testPage }) => {
      test.skip(!testSpace || !testPage, 'Test space or page not available')

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/pages/${testPage.slug}/edit`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Open attachment panel and upload
      const attachBtn = page.locator('button[title="Attachments"]')
      await attachBtn.click()

      const fileChooserPromise = page.waitForEvent('filechooser')
      await page.locator('text=Click to upload').click()
      const fileChooser = await fileChooserPromise
      await fileChooser.setFiles(tmpTextFile)

      await page.waitForResponse(
        response => response.url().includes('/attachments/') && response.request().method() === 'POST',
        { timeout: 15000 }
      )

      // Wait for UI to update
      await page.waitForTimeout(2000)

      // Verify the Attachments header shows a count
      const panelHeader = page.locator('button:has-text("Attachments")')
      const headerText = await panelHeader.textContent()
      // Should contain "Attachments" and a number
      expect(headerText).toMatch(/Attachments/)
      // Count badge should show at least 1 attachment
      const countMatch = headerText.match(/(\d+)/)
      expect(countMatch).toBeTruthy()
      expect(parseInt(countMatch[1])).toBeGreaterThanOrEqual(1)
    })

  })

})

import { test, expect, TEST_USER } from './fixtures.js'

const BASE_URL = process.env.BASE_URL || 'http://shizuha-nginx'
const WIKI_URL = `${BASE_URL}/wiki`

test.describe('Editor Macros - Callouts and Table of Contents', () => {

  test('should display callout dropdown in editor toolbar', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    // Navigate to page editor
    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // Look for the callout dropdown button (info icon with chevron)
    const calloutButton = page.locator('button:has(svg.lucide-info)')
    await expect(calloutButton).toBeVisible()
  })

  test('should display TOC button in editor toolbar', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // Look for the TOC button (list-tree icon)
    const tocButton = page.locator('button:has(svg.lucide-list-tree)')
    await expect(tocButton).toBeVisible()
  })

  test('should insert info callout when selected from dropdown', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // Click callout dropdown
    const calloutButton = page.locator('button:has(svg.lucide-info):has(svg.lucide-chevron-down)')
    await calloutButton.click()

    // Wait for dropdown menu
    await page.waitForSelector('[class*="shadow-lg"]', { timeout: 5000 })

    // Click "Info" option
    await page.click('text=Info')

    // Verify callout was inserted
    const callout = page.locator('[data-callout][data-callout-type="info"]')
    await expect(callout).toBeVisible()
  })

  test('should insert warning callout when selected from dropdown', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // Click callout dropdown
    const calloutButton = page.locator('button:has(svg.lucide-info):has(svg.lucide-chevron-down)')
    await calloutButton.click()

    // Wait for dropdown menu
    await page.waitForSelector('[class*="shadow-lg"]', { timeout: 5000 })

    // Click "Warning" option
    await page.click('text=Warning')

    // Verify warning callout was inserted
    const callout = page.locator('[data-callout][data-callout-type="warning"]')
    await expect(callout).toBeVisible()
  })

  test('should insert tip callout when selected from dropdown', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // Click callout dropdown
    const calloutButton = page.locator('button:has(svg.lucide-info):has(svg.lucide-chevron-down)')
    await calloutButton.click()

    // Wait for dropdown menu
    await page.waitForSelector('[class*="shadow-lg"]', { timeout: 5000 })

    // Click "Tip" option
    await page.click('text=Tip')

    // Verify tip callout was inserted
    const callout = page.locator('[data-callout][data-callout-type="tip"]')
    await expect(callout).toBeVisible()
  })

  test('should insert error callout when selected from dropdown', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // Click callout dropdown
    const calloutButton = page.locator('button:has(svg.lucide-info):has(svg.lucide-chevron-down)')
    await calloutButton.click()

    // Wait for dropdown menu
    await page.waitForSelector('[class*="shadow-lg"]', { timeout: 5000 })

    // Click "Error" option
    await page.click('text=Error')

    // Verify error callout was inserted
    const callout = page.locator('[data-callout][data-callout-type="error"]')
    await expect(callout).toBeVisible()
  })

  test('should insert note callout when selected from dropdown', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // Click callout dropdown
    const calloutButton = page.locator('button:has(svg.lucide-info):has(svg.lucide-chevron-down)')
    await calloutButton.click()

    // Wait for dropdown menu
    await page.waitForSelector('[class*="shadow-lg"]', { timeout: 5000 })

    // Click "Note" option
    await page.click('text=Note')

    // Verify note callout was inserted
    const callout = page.locator('[data-callout][data-callout-type="note"]')
    await expect(callout).toBeVisible()
  })

  test('should insert Table of Contents when button clicked', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // Click TOC button
    const tocButton = page.locator('button:has(svg.lucide-list-tree)')
    await tocButton.click()

    // Verify TOC was inserted
    const toc = page.locator('[data-table-of-contents]')
    await expect(toc).toBeVisible()

    // TOC should show "No headings found" initially
    await expect(page.locator('text=No headings found')).toBeVisible()
  })

  // TODO: Investigate intermittent timeout - toolbar not visible after page load in some test runs
  test.skip('TOC should update when headings are added', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    // Navigate to new page with explicit wait
    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`, { waitUntil: 'networkidle' })
    await page.waitForLoadState('domcontentloaded')

    // Wait for the editor toolbar to be ready (ensures we're on editor page)
    await page.waitForSelector('.ProseMirror', { timeout: 15000 })
    await page.waitForSelector('button:has(svg.lucide-heading-1)', { timeout: 10000 })

    // First add a heading before TOC (to test TOC picks it up)
    const editor = page.locator('.ProseMirror')
    await editor.click()

    // Add a heading using the toolbar
    const h1Button = page.locator('button:has(svg.lucide-heading-1)')
    await h1Button.click()

    // Type heading text
    await page.keyboard.type('Test Heading')
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')

    // Now insert TOC
    const tocButton = page.locator('button:has(svg.lucide-list-tree)')
    await tocButton.click()

    // Wait for TOC to appear and show the heading
    await expect(page.locator('[data-table-of-contents]')).toBeVisible({ timeout: 5000 })

    // The TOC should show the heading
    await expect(page.locator('.toc-nav')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=Test Heading').first()).toBeVisible()
  })

  test('callout should be editable', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // Insert info callout
    const calloutButton = page.locator('button:has(svg.lucide-info):has(svg.lucide-chevron-down)')
    await calloutButton.click()
    await page.click('text=Info')

    // Wait for callout to appear
    const callout = page.locator('[data-callout][data-callout-type="info"]')
    await expect(callout).toBeVisible()

    // Type inside the callout
    await callout.locator('.callout-content').click()
    await page.keyboard.type('This is important information!')

    // Verify content was added
    await expect(page.locator('text=This is important information!')).toBeVisible()
  })

  test('should have correct styling for each callout type', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    const calloutTypes = ['info', 'note', 'tip', 'warning', 'error']

    for (const type of calloutTypes) {
      // Insert callout
      const calloutButton = page.locator('button:has(svg.lucide-info):has(svg.lucide-chevron-down)')
      await calloutButton.click()

      // Click the option (capitalize first letter)
      const label = type.charAt(0).toUpperCase() + type.slice(1)
      await page.click(`text=${label}`)

      // Verify callout exists with correct type
      const callout = page.locator(`[data-callout][data-callout-type="${type}"]`)
      await expect(callout).toBeVisible()

      // Add a new line after the callout
      await page.keyboard.press('ArrowDown')
      await page.keyboard.press('Enter')
    }
  })
})

test.describe('Editor Macros - Page Save and View', () => {

  test('should save page with callout and render correctly in view', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    // Navigate to new page
    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`)
    await page.waitForSelector('.ProseMirror', { timeout: 10000 })

    // Set page title with unique timestamp
    const titleInput = page.locator('input[placeholder="Page title"]')
    await titleInput.fill(`Test Page with Callout ${Date.now()}`)

    // Insert warning callout
    const calloutButton = page.locator('button:has(svg.lucide-info):has(svg.lucide-chevron-down)')
    await calloutButton.click()
    await page.click('text=Warning')

    // Type in callout
    const callout = page.locator('[data-callout][data-callout-type="warning"]')
    await expect(callout).toBeVisible({ timeout: 5000 })
    await callout.locator('.callout-content').click()
    await page.keyboard.type('Be careful with this operation!')

    // Save the page
    const saveButton = page.locator('button:has-text("Save")')
    await saveButton.click()

    // Wait for navigation to view page
    await page.waitForURL(/\/pages\/[^/]+$/, { timeout: 15000 })

    // Wait for content to load
    await page.waitForSelector('.prose', { timeout: 10000 })

    // Verify the callout text is visible (rendered with the callout-rendered class)
    await expect(page.locator('text=Be careful with this operation!')).toBeVisible({ timeout: 10000 })

    // Verify callout styling is applied (the warning border color)
    const calloutDiv = page.locator('.callout-warning, [class*="callout-warning"]')
    await expect(calloutDiv).toBeVisible({ timeout: 5000 })
  })

  // TODO: Investigate intermittent timeout - toolbar not visible after page load in some test runs
  test.skip('should save page with TOC and render correctly in view', async ({ authenticatedPage, testSpace }) => {
    if (!testSpace) test.skip()
    const page = authenticatedPage

    // Navigate to new page with explicit wait
    await page.goto(`${WIKI_URL}/spaces/${testSpace.key}/pages/new`, { waitUntil: 'networkidle' })
    await page.waitForLoadState('domcontentloaded')

    // Wait for the editor toolbar to be ready
    await page.waitForSelector('.ProseMirror', { timeout: 15000 })
    await page.waitForSelector('button:has(svg.lucide-heading-1)', { timeout: 10000 })

    // Set page title with unique timestamp
    const titleInput = page.locator('input[placeholder="Page title"]')
    await titleInput.fill(`Test Page with TOC ${Date.now()}`)

    // First add headings (before TOC for more reliable test)
    const editor = page.locator('.ProseMirror')
    await editor.click()

    // Add first heading
    const h1Button = page.locator('button:has(svg.lucide-heading-1)')
    await h1Button.click()
    await page.keyboard.type('Introduction')
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')

    // Add second heading
    const h2Button = page.locator('button:has(svg.lucide-heading-2)')
    await h2Button.click()
    await page.keyboard.type('Getting Started')
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')

    // Add some text
    await page.keyboard.type('This is the getting started section.')
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')

    // Now insert TOC at the end
    const tocButton = page.locator('button:has(svg.lucide-list-tree)')
    await tocButton.click()

    // Verify TOC shows the headings in editor
    await expect(page.locator('[data-table-of-contents]')).toBeVisible({ timeout: 5000 })

    // Save the page
    const saveButton = page.locator('button:has-text("Save")')
    await saveButton.click()

    // Wait for navigation to view page
    await page.waitForURL(/\/pages\/[^/]+$/, { timeout: 15000 })

    // Wait for content to load
    await page.waitForSelector('.prose', { timeout: 10000 })

    // Verify headings are visible
    await expect(page.locator('h1:has-text("Introduction")')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('h2:has-text("Getting Started")')).toBeVisible({ timeout: 5000 })

    // Verify TOC renders in view mode (look for any TOC styling)
    await expect(page.locator('.toc-rendered, [class*="toc-rendered"]')).toBeVisible({ timeout: 5000 })
  })
})

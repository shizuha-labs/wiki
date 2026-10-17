import { test, expect, uniqueSpaceKey } from './fixtures.js'

/**
 * E2E tests for:
 * - Phase 1: Child page bug fix (slug filtering)
 * - Phase 2: Persistent sidebar page tree
 * - Phase 3: Move and reorder pages
 */

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Create a space and return it (with id, which SpaceCreateSerializer doesn't return) */
async function createSpace(api) {
  const key = uniqueSpaceKey().toUpperCase()
  const createRes = await api.post('spaces/', {
    data: {
      key,
      name: `Tree Test ${key}`,
      description: 'E2E page-tree test space',
      visibility: 'public',
      space_type: 'documentation',
    },
  })
  expect(createRes.ok(), `create space: ${await createRes.text()}`).toBeTruthy()

  // Fetch via detail endpoint to get the full response including id
  const getRes = await api.get(`spaces/${key}/`)
  expect(getRes.ok()).toBeTruthy()
  return getRes.json()
}

/** Create a published page and return it */
async function createPage(api, spaceId, title, parentId = null, position = 0) {
  const res = await api.post('pages/', {
    data: {
      space: spaceId,
      parent: parentId,
      title,
      content_json: {
        type: 'doc',
        content: [{ type: 'paragraph', content: [{ type: 'text', text: `Content of ${title}` }] }],
      },
      content_text: `Content of ${title}`,
      status: 'published',
      position,
    },
  })
  expect(res.ok(), `create page "${title}": ${await res.text()}`).toBeTruthy()
  return res.json()
}

// ─── Phase 1: Slug filtering bug fix ─────────────────────────────────────────

test.describe('Phase 1 — Child page slug filtering', () => {
  let space, parentPage, childPage

  test.beforeAll(async ({ authenticatedApi }) => {
    space = await createSpace(authenticatedApi)
    parentPage = await createPage(authenticatedApi, space.id, 'Parent Page P1')
    childPage = await createPage(authenticatedApi, space.id, 'Child of P1', parentPage.id)
  })

  test('listing with slug param returns only the matching page', async ({ authenticatedApi }) => {
    // Request with space_key + slug for the CHILD page
    const res = await authenticatedApi.get(
      `pages/?space_key=${space.key}&slug=${childPage.slug}`
    )
    expect(res.ok()).toBeTruthy()

    const data = await res.json()
    const pages = data.results || data
    expect(pages.length).toBe(1)
    expect(pages[0].id).toBe(childPage.id)
    expect(pages[0].slug).toBe(childPage.slug)
    expect(pages[0].title).toBe('Child of P1')
  })

  test('listing with slug param for parent returns only the parent', async ({ authenticatedApi }) => {
    const res = await authenticatedApi.get(
      `pages/?space_key=${space.key}&slug=${parentPage.slug}`
    )
    expect(res.ok()).toBeTruthy()

    const data = await res.json()
    const pages = data.results || data
    expect(pages.length).toBe(1)
    expect(pages[0].id).toBe(parentPage.id)
    expect(pages[0].title).toBe('Parent Page P1')
  })

  test('listing with non-existent slug returns empty', async ({ authenticatedApi }) => {
    const res = await authenticatedApi.get(
      `pages/?space_key=${space.key}&slug=does-not-exist-xyz`
    )
    expect(res.ok()).toBeTruthy()

    const data = await res.json()
    const pages = data.results || data
    expect(pages.length).toBe(0)
  })

  test('listing without slug returns all pages in space', async ({ authenticatedApi }) => {
    const res = await authenticatedApi.get(`pages/?space_key=${space.key}`)
    expect(res.ok()).toBeTruthy()

    const data = await res.json()
    const pages = data.results || data
    expect(pages.length).toBeGreaterThanOrEqual(2)
  })

  test('child page view shows child content, not parent', async ({ authenticatedPage, authenticatedApi }) => {
    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${space.key}/pages/${childPage.slug}`)
    await page.waitForLoadState('networkidle', { timeout: 20000 })

    // The title should be the child's title, NOT the parent's
    await expect(page.locator('h1').first()).toContainText('Child of P1', { timeout: 10000 })
    // And it should NOT show the parent's title as h1
    const h1Text = await page.locator('h1').first().textContent()
    expect(h1Text).not.toContain('Parent Page P1')
  })

  test('parent page view still shows parent content', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${space.key}/pages/${parentPage.slug}`)
    await page.waitForLoadState('networkidle', { timeout: 20000 })

    await expect(page.locator('h1').first()).toContainText('Parent Page P1', { timeout: 10000 })
  })
})

// ─── Phase 2: Persistent sidebar page tree ───────────────────────────────────

test.describe('Phase 2 — Sidebar page tree', () => {
  let space, rootPage, childPage, grandchildPage

  test.beforeAll(async ({ authenticatedApi }) => {
    space = await createSpace(authenticatedApi)
    rootPage = await createPage(authenticatedApi, space.id, 'Root A', null, 0)
    childPage = await createPage(authenticatedApi, space.id, 'Child B', rootPage.id, 0)
    grandchildPage = await createPage(authenticatedApi, space.id, 'Grandchild C', childPage.id, 0)
    // Create a sibling root page
    await createPage(authenticatedApi, space.id, 'Root D', null, 1)
  })

  test('sidebar shows page tree when inside a space', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${space.key}`)
    await page.waitForLoadState('networkidle', { timeout: 20000 })

    // Desktop sidebar (lg:fixed) should show a "Pages" heading
    const desktopSidebar = page.locator('.lg\\:fixed')
    await expect(desktopSidebar.getByRole('heading', { name: 'Pages' })).toBeVisible({ timeout: 10000 })

    // Tree should contain root pages in the desktop sidebar
    await expect(desktopSidebar.getByRole('link', { name: 'Root A', exact: true })).toBeVisible({ timeout: 5000 })
    await expect(desktopSidebar.getByRole('link', { name: 'Root D', exact: true })).toBeVisible({ timeout: 5000 })
  })

  test('space tree API returns hierarchical data', async ({ authenticatedApi }) => {
    const res = await authenticatedApi.get(`spaces/${space.key}/tree/`)
    expect(res.ok()).toBeTruthy()

    const tree = await res.json()
    expect(Array.isArray(tree)).toBeTruthy()
    expect(tree.length).toBeGreaterThanOrEqual(2) // Root A and Root D

    // Find Root A and verify children
    const rootA = tree.find(p => p.title === 'Root A')
    expect(rootA).toBeDefined()
    expect(rootA.children.length).toBe(1)
    expect(rootA.children[0].title).toBe('Child B')
    expect(rootA.children[0].children.length).toBe(1)
    expect(rootA.children[0].children[0].title).toBe('Grandchild C')
  })

  test('current page is highlighted in sidebar tree', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${space.key}/pages/${rootPage.slug}`)
    await page.waitForLoadState('networkidle', { timeout: 20000 })

    // The desktop sidebar tree link for Root A should have the highlighted class
    const desktopSidebar = page.locator('.lg\\:fixed')
    const rootALink = desktopSidebar.getByRole('link', { name: 'Root A', exact: true })
    await expect(rootALink).toBeVisible({ timeout: 10000 })

    // Check for the highlighted styling (bg-shizuha)
    const classes = await rootALink.getAttribute('class')
    expect(classes).toContain('bg-shizuha')
  })

  test('tree auto-expands to current deep page', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    // Navigate directly to the grandchild page
    await page.goto(`/wiki/spaces/${space.key}/pages/${grandchildPage.slug}`)
    await page.waitForLoadState('networkidle', { timeout: 20000 })

    // The desktop sidebar should auto-expand to show Grandchild C
    const desktopSidebar = page.locator('.lg\\:fixed')
    await expect(desktopSidebar.getByRole('link', { name: 'Grandchild C', exact: true })).toBeVisible({ timeout: 10000 })
    // And all ancestors should be visible
    await expect(desktopSidebar.getByRole('link', { name: 'Child B', exact: true })).toBeVisible({ timeout: 5000 })
    await expect(desktopSidebar.getByRole('link', { name: 'Root A', exact: true })).toBeVisible({ timeout: 5000 })
  })

  test('page tree in SpaceView main content area', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.goto(`/wiki/spaces/${space.key}`)
    await page.waitForLoadState('networkidle', { timeout: 20000 })

    // The main content area should show the page tree with page links
    // Use the Pages heading in main to scope to the page tree card
    const mainContent = page.locator('main')
    const pagesCard = mainContent.locator('h2:has-text("Pages")').locator('..')
    await expect(pagesCard).toBeVisible({ timeout: 10000 })

    // Check that root pages appear in the main page tree
    await expect(mainContent.getByRole('link', { name: 'Root A', exact: true }).first()).toBeVisible({ timeout: 5000 })
    await expect(mainContent.getByRole('link', { name: 'Root D', exact: true }).first()).toBeVisible({ timeout: 5000 })
  })
})

// ─── Phase 3: Move and reorder ───────────────────────────────────────────────

test.describe('Phase 3 — Move and reorder pages', () => {
  let space, pageA, pageB, pageC, childOfA

  test.beforeAll(async ({ authenticatedApi }) => {
    space = await createSpace(authenticatedApi)
    pageA = await createPage(authenticatedApi, space.id, 'Page A', null, 0)
    pageB = await createPage(authenticatedApi, space.id, 'Page B', null, 1)
    pageC = await createPage(authenticatedApi, space.id, 'Page C', null, 2)
    childOfA = await createPage(authenticatedApi, space.id, 'Child of A', pageA.id, 0)
  })

  test.describe('Move endpoint', () => {
    test('should move a root page under another page', async ({ authenticatedApi }) => {
      // Move Page C under Page B
      const res = await authenticatedApi.post(`pages/${pageC.id}/move/`, {
        data: { parent: pageB.id, position: 0 },
      })
      expect(res.ok()).toBeTruthy()

      const moved = await res.json()
      expect(moved.parent).toBe(pageB.id)
      expect(moved.position).toBe(0)

      // Verify via tree
      const treeRes = await authenticatedApi.get(`spaces/${space.key}/tree/`)
      const tree = await treeRes.json()
      const b = tree.find(p => p.title === 'Page B')
      expect(b).toBeDefined()
      expect(b.children.length).toBe(1)
      expect(b.children[0].title).toBe('Page C')

      // Move Page C back to root for further tests
      await authenticatedApi.post(`pages/${pageC.id}/move/`, {
        data: { parent: null, position: 2 },
      })
    })

    test('should move a child page to root', async ({ authenticatedApi }) => {
      // Move Child of A to root
      const res = await authenticatedApi.post(`pages/${childOfA.id}/move/`, {
        data: { parent: null, position: 3 },
      })
      expect(res.ok()).toBeTruthy()

      const moved = await res.json()
      expect(moved.parent).toBeNull()

      // Move back for further tests
      await authenticatedApi.post(`pages/${childOfA.id}/move/`, {
        data: { parent: pageA.id, position: 0 },
      })
    })

    test('should prevent circular move (page under itself)', async ({ authenticatedApi }) => {
      // Try to move Page A under its own child
      const res = await authenticatedApi.post(`pages/${pageA.id}/move/`, {
        data: { parent: childOfA.id },
      })
      expect(res.status()).toBe(400)

      const body = await res.json()
      expect(body.error).toContain('Cannot move page under itself')
    })

    test('should return 404 for non-existent parent', async ({ authenticatedApi }) => {
      const fakeId = '00000000-0000-0000-0000-000000000099'
      const res = await authenticatedApi.post(`pages/${pageA.id}/move/`, {
        data: { parent: fakeId },
      })
      expect(res.status()).toBe(404)
    })
  })

  test.describe('Reorder endpoint', () => {
    test('should reorder sibling pages', async ({ authenticatedApi }) => {
      // Current order: A(0), B(1), C(2)
      // New order: C, A, B
      const res = await authenticatedApi.post('pages/reorder/', {
        data: { page_ids: [pageC.id, pageA.id, pageB.id] },
      })
      expect(res.ok()).toBeTruthy()

      const body = await res.json()
      expect(body.status).toBe('ok')

      // Verify new positions
      const aRes = await authenticatedApi.get(`pages/${pageA.id}/`)
      const aData = await aRes.json()
      expect(aData.position).toBe(1)

      const bRes = await authenticatedApi.get(`pages/${pageB.id}/`)
      const bData = await bRes.json()
      expect(bData.position).toBe(2)

      const cRes = await authenticatedApi.get(`pages/${pageC.id}/`)
      const cData = await cRes.json()
      expect(cData.position).toBe(0)
    })

    test('should reflect new order in space tree', async ({ authenticatedApi }) => {
      // After reorder: C(0), A(1), B(2)
      const treeRes = await authenticatedApi.get(`spaces/${space.key}/tree/`)
      const tree = await treeRes.json()

      // Tree is ordered by position, title — so C should come first
      const titles = tree.map(p => p.title)
      const idxC = titles.indexOf('Page C')
      const idxA = titles.indexOf('Page A')
      const idxB = titles.indexOf('Page B')
      expect(idxC).toBeLessThan(idxA)
      expect(idxA).toBeLessThan(idxB)
    })
  })

  test.describe('Frontend API methods', () => {
    test('movePage API method works via the UI service', async ({ authenticatedApi }) => {
      // This tests the same endpoint the frontend would call
      // Move page B under page A via the /move/ endpoint
      const res = await authenticatedApi.post(`pages/${pageB.id}/move/`, {
        data: { parent: pageA.id, position: 1 },
      })
      expect(res.ok()).toBeTruthy()
      const moved = await res.json()
      expect(moved.parent).toBe(pageA.id)

      // Move back
      await authenticatedApi.post(`pages/${pageB.id}/move/`, {
        data: { parent: null, position: 2 },
      })
    })

    test('reorderPages API method works via the UI service', async ({ authenticatedApi }) => {
      // Restore order: A, B, C
      const res = await authenticatedApi.post('pages/reorder/', {
        data: { page_ids: [pageA.id, pageB.id, pageC.id] },
      })
      expect(res.ok()).toBeTruthy()

      // Verify
      const aRes = await authenticatedApi.get(`pages/${pageA.id}/`)
      expect((await aRes.json()).position).toBe(0)
    })
  })

  test.describe('Drag-and-drop UI elements', () => {
    test('page tree nodes have drag handles in sidebar', async ({ authenticatedPage }) => {
      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${space.key}`)
      await page.waitForLoadState('networkidle', { timeout: 20000 })

      // The sidebar page tree should have GripVertical drag handle icons
      const sidebar = page.locator('nav')
      // Drag handles are SVG icons with lucide's GripVertical
      const dragHandles = sidebar.locator('[draggable="true"]')
      // There should be at least one drag handle (one per visible tree node)
      const count = await dragHandles.count()
      expect(count).toBeGreaterThanOrEqual(1)
    })

    test('page tree nodes in SpaceView main area have drag handles', async ({ authenticatedPage }) => {
      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${space.key}`)
      await page.waitForLoadState('networkidle', { timeout: 20000 })

      const mainContent = page.locator('main')
      const dragHandles = mainContent.locator('[draggable="true"]')
      const count = await dragHandles.count()
      expect(count).toBeGreaterThanOrEqual(1)
    })
  })
})

// ─── Integration: Full flow ──────────────────────────────────────────────────

test.describe('Full integration flow', () => {
  test('create hierarchy, navigate to child, verify correct content', async ({ authenticatedApi, authenticatedPage }) => {
    // Setup: create space with parent and child
    const space = await createSpace(authenticatedApi)
    const parent = await createPage(authenticatedApi, space.id, 'Integration Parent')
    const child = await createPage(authenticatedApi, space.id, 'Integration Child', parent.id)

    const page = authenticatedPage

    // Navigate to child page by slug
    await page.goto(`/wiki/spaces/${space.key}/pages/${child.slug}`)
    await page.waitForLoadState('networkidle', { timeout: 20000 })

    // Verify: child page title is shown (not parent's)
    await expect(page.locator('h1').first()).toContainText('Integration Child', { timeout: 10000 })

    // Verify: breadcrumbs show the parent in the trail (in main content area)
    const mainContent = page.locator('main')
    await expect(mainContent.getByRole('link', { name: 'Integration Parent' })).toBeVisible({ timeout: 5000 })

    // Verify: desktop sidebar tree shows both pages
    const desktopSidebar = page.locator('.lg\\:fixed')
    await expect(desktopSidebar.getByRole('link', { name: 'Integration Parent', exact: true })).toBeVisible({ timeout: 5000 })
    await expect(desktopSidebar.getByRole('link', { name: 'Integration Child', exact: true })).toBeVisible({ timeout: 5000 })
  })

  test('reorder then verify tree order updates', async ({ authenticatedApi }) => {
    const space = await createSpace(authenticatedApi)
    const p1 = await createPage(authenticatedApi, space.id, 'First', null, 0)
    const p2 = await createPage(authenticatedApi, space.id, 'Second', null, 1)
    const p3 = await createPage(authenticatedApi, space.id, 'Third', null, 2)

    // Reverse the order
    const reorderRes = await authenticatedApi.post('pages/reorder/', {
      data: { page_ids: [p3.id, p2.id, p1.id] },
    })
    expect(reorderRes.ok()).toBeTruthy()

    // Check tree reflects new order
    const treeRes = await authenticatedApi.get(`spaces/${space.key}/tree/`)
    const tree = await treeRes.json()
    expect(tree[0].title).toBe('Third')
    expect(tree[1].title).toBe('Second')
    expect(tree[2].title).toBe('First')
  })

  test('move page and verify tree restructures', async ({ authenticatedApi }) => {
    const space = await createSpace(authenticatedApi)
    const p1 = await createPage(authenticatedApi, space.id, 'Move Root')
    const p2 = await createPage(authenticatedApi, space.id, 'Move Target')

    // Verify both are root pages initially
    let treeRes = await authenticatedApi.get(`spaces/${space.key}/tree/`)
    let tree = await treeRes.json()
    expect(tree.length).toBe(2)

    // Move p1 under p2
    const moveRes = await authenticatedApi.post(`pages/${p1.id}/move/`, {
      data: { parent: p2.id, position: 0 },
    })
    expect(moveRes.ok()).toBeTruthy()

    // Verify tree now has p1 as child of p2
    treeRes = await authenticatedApi.get(`spaces/${space.key}/tree/`)
    tree = await treeRes.json()
    expect(tree.length).toBe(1) // only p2 at root
    expect(tree[0].title).toBe('Move Target')
    expect(tree[0].children.length).toBe(1)
    expect(tree[0].children[0].title).toBe('Move Root')
  })
})

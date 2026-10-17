import { test, expect, TEST_USER, uniqueSpaceKey } from './fixtures.js'

/**
 * Space Settings E2E tests for Shizuha Wiki
 *
 * Tests cover:
 * - Access control (only admins can access settings)
 * - General settings (name, description, type, color)
 * - Visibility changes
 * - Member management (add, update role, remove)
 */

test.describe('Space Settings', () => {

  test.describe('Access Control', () => {

    test('should allow admin to access settings', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      // The test user should be admin (they created the space)
      const response = await authenticatedApi.get(`spaces/${testSpace.key}/members/`)
      expect(response.ok()).toBeTruthy()

      const members = await response.json()
      const currentUserMember = members.find(m => m.role === 'admin')
      expect(currentUserMember).toBeDefined()
    })

    test('should show settings button for admin in UI', async ({ authenticatedPage, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Wait for the page to fully load
      await page.waitForSelector('h1', { timeout: 10000 })

      // Settings button should be visible for admins (in main content area, not sidebar nav)
      const settingsButton = page.locator('main a:has-text("Settings"), [role="main"] a:has-text("Settings"), a[href*="/settings"]:has-text("Settings")').filter({ hasText: 'Settings' }).last()
      await expect(settingsButton).toBeVisible({ timeout: 5000 })
    })

    test('should navigate to settings page', async ({ authenticatedPage, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Click the space settings button (specific to this space, not the global settings nav link)
      await page.click(`a[href*="/spaces/${testSpace.key}/settings"]`)

      // Should navigate to settings page
      await page.waitForURL(/.*\/settings.*/, { timeout: 10000 })

      // Should show settings heading
      await expect(page.locator('h1:has-text("Space Settings")')).toBeVisible({ timeout: 5000 })
    })

  })

  test.describe('General Settings API', () => {

    test('should update space name', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const newName = `Updated Space ${Date.now()}`
      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/`, {
        data: { name: newName }
      })

      expect(response.ok()).toBeTruthy()
      const updated = await response.json()
      expect(updated.name).toBe(newName)
    })

    test('should update space description', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const newDescription = `Updated description ${Date.now()}`
      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/`, {
        data: { description: newDescription }
      })

      expect(response.ok()).toBeTruthy()
      const updated = await response.json()
      expect(updated.description).toBe(newDescription)
    })

    test('should update space type', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/`, {
        data: { space_type: 'knowledge_base' }
      })

      expect(response.ok()).toBeTruthy()
      const updated = await response.json()
      expect(updated.space_type).toBe('knowledge_base')
    })

    test('should update space color', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const newColor = '#FF5733'
      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/`, {
        data: { color: newColor }
      })

      expect(response.ok()).toBeTruthy()
      const updated = await response.json()
      expect(updated.color).toBe(newColor)
    })

  })

  test.describe('Visibility Settings API', () => {

    test('should update visibility to public', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/`, {
        data: { visibility: 'public' }
      })

      expect(response.ok()).toBeTruthy()
      const updated = await response.json()
      expect(updated.visibility).toBe('public')
    })

    test('should update visibility to private', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/`, {
        data: { visibility: 'private' }
      })

      expect(response.ok()).toBeTruthy()
      const updated = await response.json()
      expect(updated.visibility).toBe('private')
    })

    test('should update visibility to org', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/`, {
        data: { visibility: 'org' }
      })

      expect(response.ok()).toBeTruthy()
      const updated = await response.json()
      expect(updated.visibility).toBe('org')
    })

  })

  test.describe('Member Management API', () => {

    test('should list space members', async ({ authenticatedApi, testSpace }) => {
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
      // At least one admin
      const adminMembers = members.filter(m => m.role === 'admin')
      expect(adminMembers.length).toBeGreaterThanOrEqual(1)
    })

    test('should update member role via PATCH', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      // First get current members
      const listResponse = await authenticatedApi.get(`spaces/${testSpace.key}/members/`)
      expect(listResponse.ok()).toBeTruthy()

      const members = await listResponse.json()
      // We need at least one member that is not the owner to test role change
      // Since test user is likely the owner/admin, we can only test the endpoint works
      // without actually changing our own role (which should be blocked)

      // Find a member (preferably not self)
      const member = members[0]
      expect(member).toBeDefined()

      // Try to update to same role (should succeed without changing anything meaningful)
      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/members/`, {
        data: {
          user_id: member.user_id,
          role: 'admin' // Keep as admin
        }
      })

      // This should work for the owner
      expect(response.ok()).toBeTruthy()
      const updated = await response.json()
      expect(updated.role).toBe('admin')
    })

    test('should reject invalid role', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const listResponse = await authenticatedApi.get(`spaces/${testSpace.key}/members/`)
      const members = await listResponse.json()
      const member = members[0]

      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/members/`, {
        data: {
          user_id: member.user_id,
          role: 'invalid_role'
        }
      })

      expect(response.ok()).toBeFalsy()
      expect(response.status()).toBe(400)
    })

    test('should reject PATCH without user_id', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/members/`, {
        data: {
          role: 'editor'
        }
      })

      expect(response.ok()).toBeFalsy()
      expect(response.status()).toBe(400)
    })

    test('should reject PATCH without role', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const listResponse = await authenticatedApi.get(`spaces/${testSpace.key}/members/`)
      const members = await listResponse.json()
      const member = members[0]

      const response = await authenticatedApi.patch(`spaces/${testSpace.key}/members/`, {
        data: {
          user_id: member.user_id
        }
      })

      expect(response.ok()).toBeFalsy()
      expect(response.status()).toBe(400)
    })

  })

  test.describe('Settings UI', () => {

    test('should display General tab content', async ({ authenticatedPage, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/settings`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Should show General tab by default
      await expect(page.locator('button:has-text("General")')).toBeVisible({ timeout: 10000 })

      // Should show form fields
      await expect(page.getByText('Space Key', { exact: true })).toBeVisible({ timeout: 10000 })
      await expect(page.getByText('Name', { exact: true })).toBeVisible()
      await expect(page.getByText('Description', { exact: true })).toBeVisible()
    })

    test('should display Access tab content', async ({ authenticatedPage, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/settings`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Click Access tab
      await page.click('button:has-text("Access")')

      // Should show visibility selector
      await expect(page.locator('text=Space Visibility')).toBeVisible({ timeout: 5000 })
      await expect(page.locator('text=Public')).toBeVisible()
      await expect(page.locator('text=Private')).toBeVisible()
      await expect(page.getByText('Organization', { exact: true })).toBeVisible()

      // Should show members section
      await expect(page.getByRole('heading', { name: 'Members' })).toBeVisible()
      await expect(page.locator('button:has-text("Add Member")')).toBeVisible()
    })

    test('should show save button when changes are made', async ({ authenticatedPage, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/settings`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Save button should not be visible initially
      await expect(page.locator('button:has-text("Save Changes")')).not.toBeVisible({ timeout: 3000 })

      // Change the name
      const nameInput = page.locator('input').nth(1) // Second input (after Space Key)
      await nameInput.fill('Modified Name ' + Date.now())

      // Save button should appear
      await expect(page.locator('button:has-text("Save Changes")')).toBeVisible({ timeout: 5000 })
    })

    test('should open Add Member modal', async ({ authenticatedPage, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/settings`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Go to Access tab
      await page.click('button:has-text("Access")')
      await page.waitForTimeout(500)

      // Click Add Member button
      await page.click('button:has-text("Add Member")')

      // Modal should appear
      await expect(page.locator('h2:has-text("Add Member")')).toBeVisible({ timeout: 5000 })
      await expect(page.locator('input[placeholder*="Search"]')).toBeVisible()
    })

    test('should close Add Member modal', async ({ authenticatedPage, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const page = authenticatedPage
      await page.goto(`/wiki/spaces/${testSpace.key}/settings`)
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Go to Access tab and open modal
      await page.click('button:has-text("Access")')
      await page.waitForTimeout(500)
      await page.click('button:has-text("Add Member")')

      // Modal should be visible
      await expect(page.locator('h2:has-text("Add Member")')).toBeVisible({ timeout: 5000 })

      // Click cancel
      await page.click('button:has-text("Cancel")')

      // Modal should be hidden
      await expect(page.locator('h2:has-text("Add Member")')).not.toBeVisible({ timeout: 3000 })
    })

  })

  test.describe('User Search API', () => {

    test('should return empty for short query', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      const response = await authenticatedApi.get(`spaces/${testSpace.key}/search_users/?q=a`)
      expect(response.ok()).toBeTruthy()

      const users = await response.json()
      expect(Array.isArray(users)).toBeTruthy()
      expect(users.length).toBe(0)
    })

    test('should search users', async ({ authenticatedApi, testSpace }) => {
      if (!testSpace) {
        test.skip('No test space available')
        return
      }

      // Search for test user (should find nothing since they're already a member)
      const response = await authenticatedApi.get(`spaces/${testSpace.key}/search_users/?q=test`)

      // Note: This may fail if shizuha-id is not running or not configured
      // The endpoint should at least respond
      if (response.ok()) {
        const users = await response.json()
        expect(Array.isArray(users)).toBeTruthy()
        // Test user should be filtered out since they're already a member
      } else {
        // Service unavailable is acceptable in test environment
        expect([502, 503]).toContain(response.status())
      }
    })

  })

})

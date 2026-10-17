import { useState, useRef, useEffect } from 'react'
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Home,
  BookOpen,
  Search,
  Settings,
  Menu,
  X,
  Plus,
  ChevronDown,
  LogOut,
  Moon,
  Sun,
  Building2,
  Compass,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useSpace } from '../contexts/SpaceContext'
import { useTheme } from '../hooks/useTheme'
import { spacesApi } from '../services/api'
import AppSwitcher from './AppSwitcher'
import { useEnabledServices } from '@shizuha/ui'
import PageTree from './PageTree'
import GlobalSearch from './GlobalSearch'

const navigation = [
  { name: 'Dashboard', href: '/', icon: Home },
  { name: 'Atlas', href: '/atlas', icon: Compass, external: true },
  { name: 'Spaces', href: '/spaces', icon: BookOpen },
  { name: 'Search', href: '/search', icon: Search },
  { name: 'Settings', href: '/settings', icon: Settings },
]

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  const { user, logout, organization, organizations, orgsError, switchOrganization } = useAuth()
  const { spaces, currentSpace, switchSpace } = useSpace()
  const { theme, toggleTheme } = useTheme()
  const enabledServices = useEnabledServices()

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Mobile sidebar */}
      <div className={`wiki-chrome fixed inset-0 z-50 lg:hidden ${sidebarOpen ? '' : 'hidden'}`}>
        <div className="fixed inset-0 bg-gray-900/80" onClick={() => setSidebarOpen(false)} />
        <div className="fixed inset-y-0 left-0 flex w-72 flex-col bg-white dark:bg-gray-800">
          <div className="flex h-16 items-center justify-between px-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-3">
              <AppSwitcher currentAppId="wiki" enabledServices={enabledServices} />
              <Link to="/" className="flex items-center gap-2">
                <BookOpen className="h-8 w-8 text-shizuha-600" />
                <span className="text-xl font-bold text-gray-900 dark:text-white">Wiki</span>
              </Link>
            </div>
            <button onClick={() => setSidebarOpen(false)}>
              <X className="h-6 w-6 text-gray-500" />
            </button>
          </div>
          <nav className="flex-1 overflow-y-auto p-4">
            <SidebarContent
              navigation={navigation}
              location={location}
              spaces={spaces}
              currentSpace={currentSpace}
              switchSpace={switchSpace}
            />
          </nav>
          {/* Mobile sidebar footer with theme toggle and user */}
          <div className="p-4 border-t border-gray-200 dark:border-gray-700">
            <button
              onClick={toggleTheme}
              className="w-full flex items-center gap-3 px-3 py-2 mb-3 rounded-lg text-sm font-medium hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-gray-700 dark:text-gray-300"
            >
              {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
              {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            </button>
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-shizuha-600 flex items-center justify-center text-white font-medium">
                {user?.username?.[0]?.toUpperCase() || 'U'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                  {user?.username || 'User'}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                  {user?.email}
                </p>
              </div>
              <button
                onClick={logout}
                className="p-2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                title="Log out"
              >
                <LogOut className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Desktop sidebar */}
      <div className="wiki-chrome hidden lg:fixed lg:inset-y-0 lg:flex lg:w-72 lg:flex-col">
        <div className="flex flex-col flex-grow bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700">
          <div className="flex h-16 items-center px-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-3">
              <AppSwitcher currentAppId="wiki" enabledServices={enabledServices} />
              <Link to="/" className="flex items-center gap-2">
                <BookOpen className="h-8 w-8 text-shizuha-600" />
                <span className="text-xl font-bold text-gray-900 dark:text-white">Shizuha Wiki</span>
              </Link>
            </div>
          </div>
          <nav className="flex-1 overflow-y-auto p-4">
            <SidebarContent
              navigation={navigation}
              location={location}
              spaces={spaces}
              currentSpace={currentSpace}
              switchSpace={switchSpace}
            />
          </nav>
          <div className="p-4 border-t border-gray-200 dark:border-gray-700">
            {/* Theme toggle */}
            <button
              onClick={toggleTheme}
              className="w-full flex items-center gap-3 px-3 py-2 mb-3 rounded-lg text-sm font-medium hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-gray-700 dark:text-gray-300"
            >
              {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
              {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            </button>
            {/* User info */}
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-shizuha-600 flex items-center justify-center text-white font-medium">
                {user?.username?.[0]?.toUpperCase() || 'U'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                  {user?.username || 'User'}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                  {user?.email}
                </p>
              </div>
              <button
                onClick={logout}
                className="p-2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                title="Log out"
              >
                <LogOut className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="wiki-shell lg:pl-72">
        {/* Top header */}
        <header className="wiki-chrome sticky top-0 z-40 flex h-16 items-center gap-x-4 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 shadow-sm sm:px-6 lg:px-8">
          <button
            type="button"
            className="lg:hidden -m-2.5 p-2.5 text-gray-700 dark:text-gray-200"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="h-6 w-6" />
          </button>

          <div className="flex flex-1 gap-x-4 self-stretch lg:gap-x-6">
            {/* Organization switcher */}
            <OrganizationSwitcher
              organization={organization}
              organizations={organizations}
              orgsError={orgsError}
              switchOrganization={switchOrganization}
            />

            {/* Space selector dropdown */}
            {currentSpace && (
              <SpaceDropdown
                spaces={spaces}
                currentSpace={currentSpace}
                switchSpace={switchSpace}
              />
            )}

            <div className="flex items-center gap-x-4 ml-auto">
              <Link
                to={currentSpace ? `/spaces/${currentSpace.key}/pages/new` : '/spaces'}
                className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 transition-colors"
              >
                <Plus className="h-4 w-4" />
                <span className="hidden sm:inline">New Page</span>
              </Link>
            </div>
          </div>
        </header>

        {/* Global search bar - desktop */}
        <div className="wiki-chrome sticky top-16 z-30 bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border-b border-gray-200 dark:border-gray-700 hidden lg:block">
          <div className="px-6 py-3">
            <GlobalSearch />
          </div>
        </div>

        {/* Global search bar - mobile */}
        <div className="wiki-chrome lg:hidden px-4 py-3 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
          <GlobalSearch />
        </div>

        {/* Page content */}
        <main className="wiki-main p-4 sm:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function OrganizationSwitcher({ organization, organizations, orgsError, switchOrganization }) {
  const [isOpen, setIsOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // PLAT-8302 truth-audit: a 401/403 from /admin/api/organizations/ is an
  // access-denied state, NOT an empty membership set — the JWT may hold real
  // memberships the seat cannot read through this API. Only a successful
  // load with an actually-empty set may render "No Organization".
  const isAuthzDenied = Boolean(
    orgsError && (orgsError.status === 401 || orgsError.status === 403)
  )
  const orgName = organization?.name
    || (isAuthzDenied ? 'Organization access denied' : 'No Organization')
  const hasMultiple = organizations.length > 1
  const orgTitle = isAuthzDenied
    ? `Admin API returned ${orgsError.status}${orgsError.code ? ` (${orgsError.code})` : ''} — this is not an empty organization list; your memberships may exist but this seat lacks Admin service access`
    : (hasMultiple ? 'Switch organization' : `Organization: ${orgName}`)

  return (
    <div className="relative flex items-center" ref={menuRef}>
      <button
        onClick={() => hasMultiple && setIsOpen(!isOpen)}
        className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border transition-colors ${
          hasMultiple
            ? 'text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-700 border-gray-200 dark:border-gray-600 cursor-pointer'
            : 'text-gray-500 dark:text-gray-400 border-transparent cursor-default'
        }`}
        title={orgTitle}
      >
        <Building2 className="h-4 w-4 flex-shrink-0" />
        <span className="max-w-40 truncate">{orgName}</span>
        {hasMultiple && <ChevronDown className={`h-3.5 w-3.5 transition-transform ${isOpen ? 'rotate-180' : ''}`} />}
      </button>

      {isOpen && hasMultiple && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute left-0 top-full mt-1 w-72 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-20 max-h-80 overflow-y-auto">
            <div className="px-4 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">
              Switch Organization
            </div>
            {organizations.map((org) => (
              <button
                key={org.id}
                onClick={() => {
                  switchOrganization(org)
                  setIsOpen(false)
                }}
                className={`flex items-center w-full px-4 py-2.5 text-sm hover:bg-gray-100 dark:hover:bg-gray-700 ${
                  organization?.id === org.id ? 'bg-shizuha-50 dark:bg-shizuha-900/30 text-shizuha-700 dark:text-shizuha-300' : 'text-gray-700 dark:text-gray-300'
                }`}
              >
                <Building2 className="h-4 w-4 mr-2.5 flex-shrink-0" />
                <div className="flex-1 text-left min-w-0">
                  <span className="block truncate">{org.name}</span>
                  {org.slug && <span className="block text-xs text-gray-400 dark:text-gray-500 truncate">{org.slug}</span>}
                </div>
                {organization?.id === org.id && (
                  <span className="ml-2 text-shizuha-600 flex-shrink-0">✓</span>
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function SpaceDropdown({ spaces, currentSpace, switchSpace }) {
  const [isOpen, setIsOpen] = useState(false)
  const navigate = useNavigate()

  const handleSpaceSelect = (space) => {
    switchSpace(space.key)
    navigate(`/spaces/${space.key}`)
    setIsOpen(false)
  }

  return (
    <div className="relative flex items-center">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
      >
        <span
          className="w-3 h-3 rounded-full"
          style={{ backgroundColor: currentSpace.color }}
        />
        <span className="text-sm font-medium text-gray-900 dark:text-white">
          {currentSpace.name}
        </span>
        <ChevronDown className={`h-4 w-4 text-gray-500 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          />
          {/* Dropdown */}
          <div className="absolute left-0 top-full mt-1 z-20 w-64 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 max-h-80 overflow-y-auto">
            {spaces.map((space) => (
              <button
                key={space.id}
                onClick={() => handleSpaceSelect(space)}
                className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 ${
                  space.key === currentSpace.key ? 'bg-gray-50 dark:bg-gray-700/50' : ''
                }`}
              >
                <span
                  className="w-3 h-3 rounded-full flex-shrink-0"
                  style={{ backgroundColor: space.color }}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {space.name}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {space.key}
                  </p>
                </div>
                {space.key === currentSpace.key && (
                  <span className="text-shizuha-600">✓</span>
                )}
              </button>
            ))}
            {spaces.length === 0 && (
              <p className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">
                No spaces available
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function SidebarContent({ navigation, location, spaces, currentSpace, switchSpace }) {
  // Detect if we're inside a space
  const spaceMatch = location.pathname.match(/\/spaces\/([^/]+)/)
  const activeSpaceKey = spaceMatch?.[1]
  const pageMatch = location.pathname.match(/\/spaces\/[^/]+\/pages\/([^/]+)/)
  const currentSlug = pageMatch?.[1]

  // Fetch page tree when inside a space
  const { data: pageTree = [] } = useQuery({
    queryKey: ['space', activeSpaceKey, 'tree'],
    queryFn: () => spacesApi.getTree(activeSpaceKey).then(r => r.data),
    enabled: !!activeSpaceKey,
  })

  return (
    <div className="space-y-6">
      {/* Main navigation */}
      <ul className="space-y-1">
        {navigation.map((item) => {
          const isActive = location.pathname === item.href ||
            (item.href !== '/' && location.pathname.startsWith(item.href))
          const className = `flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
            isActive
              ? 'bg-shizuha-50 dark:bg-shizuha-900/50 text-shizuha-700 dark:text-shizuha-300'
              : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
          }`
          return (
            <li key={item.name}>
              {item.external ? (
                <a href={item.href} className={className}>
                  <item.icon className="h-5 w-5" />
                  {item.name}
                </a>
              ) : (
              <Link
                to={item.href}
                className={className}
              >
                <item.icon className="h-5 w-5" />
                {item.name}
              </Link>
              )}
            </li>
          )
        })}
      </ul>

      {/* Spaces */}
      <div>
        <div className="flex items-center justify-between px-3 mb-2">
          <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            Spaces
          </h3>
          <Link
            to="/spaces"
            className="text-xs text-shizuha-600 dark:text-shizuha-400 hover:underline"
          >
            View all
          </Link>
        </div>
        <ul className="space-y-1">
          {spaces.slice(0, 5).map((space) => {
            const isActive = currentSpace?.key === space.key ||
              location.pathname.includes(`/spaces/${space.key}`)
            return (
              <li key={space.id}>
                <Link
                  to={`/spaces/${space.key}`}
                  onClick={() => switchSpace(space.key)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors text-left ${
                    isActive
                      ? 'bg-gray-100 dark:bg-gray-700'
                      : 'hover:bg-gray-100 dark:hover:bg-gray-700'
                  }`}
                >
                  <span
                    className="w-3 h-3 rounded-full flex-shrink-0"
                    style={{ backgroundColor: space.color }}
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300 truncate">
                    {space.name}
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      </div>

      {/* Page tree for active space */}
      {activeSpaceKey && pageTree.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider px-3 mb-2">
            Pages
          </h3>
          <PageTree
            pages={pageTree}
            spaceKey={activeSpaceKey}
            currentSlug={currentSlug}
            compact
            enableDragDrop
          />
        </div>
      )}
    </div>
  )
}

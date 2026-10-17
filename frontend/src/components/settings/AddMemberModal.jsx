import { useState, useEffect, useRef } from 'react'
import { X, Search, User, Loader2 } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { spacesApi } from '../../services/api'
import RoleBadge from './RoleBadge'

const roleOptions = [
  { value: 'viewer', label: 'Viewer', description: 'Read-only access' },
  { value: 'editor', label: 'Editor', description: 'Can edit pages' },
  { value: 'admin', label: 'Admin', description: 'Full control over space' },
]

export default function AddMemberModal({ isOpen, onClose, spaceKey, onAdd }) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedUser, setSelectedUser] = useState(null)
  const [selectedRole, setSelectedRole] = useState('viewer')
  const [isAdding, setIsAdding] = useState(false)
  const inputRef = useRef(null)

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setSearchQuery('')
      setSelectedUser(null)
      setSelectedRole('viewer')
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [isOpen])

  // Search users
  const { data: searchResults = [], isLoading: isSearching } = useQuery({
    queryKey: ['userSearch', spaceKey, searchQuery],
    queryFn: async () => {
      const response = await spacesApi.searchUsers(spaceKey, searchQuery)
      return response.data
    },
    enabled: isOpen && searchQuery.length >= 2,
    staleTime: 30000,
  })

  const handleAdd = async () => {
    if (!selectedUser) return

    setIsAdding(true)
    try {
      await onAdd(selectedUser.id, selectedRole)
      onClose()
    } catch (error) {
      console.error('Failed to add member:', error)
    } finally {
      setIsAdding(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Add Member
          </h2>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 rounded"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* Search input */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Search Users
            </label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                ref={inputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by name or email..."
                className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-500 focus:ring-2 focus:ring-shizuha-500 focus:border-transparent"
              />
              {isSearching && (
                <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 animate-spin" />
              )}
            </div>
          </div>

          {/* Search results */}
          {searchQuery.length >= 2 && (
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg max-h-48 overflow-y-auto">
              {searchResults.length > 0 ? (
                searchResults.map((user) => (
                  <button
                    key={user.id}
                    onClick={() => setSelectedUser(user)}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 ${
                      selectedUser?.id === user.id ? 'bg-shizuha-50 dark:bg-shizuha-900/20' : ''
                    }`}
                  >
                    <div className="h-8 w-8 rounded-full bg-shizuha-600 flex items-center justify-center text-white text-sm font-medium flex-shrink-0">
                      {user.username?.[0]?.toUpperCase() || user.email?.[0]?.toUpperCase() || '?'}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                        {user.username || user.first_name || 'Unknown'}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                        {user.email}
                      </p>
                    </div>
                    {selectedUser?.id === user.id && (
                      <span className="text-shizuha-600 text-lg">✓</span>
                    )}
                  </button>
                ))
              ) : !isSearching ? (
                <div className="px-3 py-4 text-center text-sm text-gray-500 dark:text-gray-400">
                  <User className="mx-auto h-8 w-8 mb-2 opacity-50" />
                  No users found
                </div>
              ) : null}
            </div>
          )}

          {/* Selected user */}
          {selectedUser && (
            <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
              <p className="text-sm text-gray-600 dark:text-gray-300 mb-2">Selected user:</p>
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-full bg-shizuha-600 flex items-center justify-center text-white font-medium">
                  {selectedUser.username?.[0]?.toUpperCase() || selectedUser.email?.[0]?.toUpperCase() || '?'}
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">
                    {selectedUser.username || selectedUser.first_name || 'Unknown'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {selectedUser.email}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Role selector */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Role
            </label>
            <div className="space-y-2">
              {roleOptions.map((option) => (
                <label
                  key={option.value}
                  className={`flex items-center gap-3 p-2 rounded-lg border cursor-pointer transition-colors ${
                    selectedRole === option.value
                      ? 'border-shizuha-500 bg-shizuha-50 dark:bg-shizuha-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                  }`}
                >
                  <input
                    type="radio"
                    name="role"
                    value={option.value}
                    checked={selectedRole === option.value}
                    onChange={(e) => setSelectedRole(e.target.value)}
                    className="sr-only"
                  />
                  <RoleBadge role={option.value} />
                  <span className="text-sm text-gray-600 dark:text-gray-400">
                    {option.description}
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-4 py-3 border-t border-gray-200 dark:border-gray-700">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleAdd}
            disabled={!selectedUser || isAdding}
            className="px-4 py-2 text-sm font-medium text-white bg-shizuha-600 hover:bg-shizuha-700 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isAdding && <Loader2 className="h-4 w-4 animate-spin" />}
            Add Member
          </button>
        </div>
      </div>
    </div>
  )
}

import { useState } from 'react'
import { Trash2, ChevronDown } from 'lucide-react'
import RoleBadge from './RoleBadge'

const roleOptions = [
  { value: 'admin', label: 'Admin', description: 'Full control over space' },
  { value: 'editor', label: 'Editor', description: 'Can edit pages' },
  { value: 'viewer', label: 'Viewer', description: 'Read-only access' },
]

export default function MembersTable({
  members = [],
  currentUserId,
  ownerId,
  onRoleChange,
  onRemove,
  isUpdating = false,
}) {
  const [openDropdown, setOpenDropdown] = useState(null)

  const handleRoleChange = (userId, role) => {
    onRoleChange(userId, role)
    setOpenDropdown(null)
  }

  const isOwner = (userId) => userId === ownerId
  const isSelf = (userId) => userId === currentUserId

  // Count admins to prevent removing the last one
  const adminCount = members.filter((m) => m.role === 'admin').length

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
          Members ({members.length})
        </label>
      </div>

      {members.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400 py-4 text-center">
          No members yet
        </p>
      ) : (
        <div className="border border-gray-200 dark:border-gray-700 rounded-lg divide-y divide-gray-200 dark:divide-gray-700">
          {members.map((member) => {
            const canChangeRole = !isOwner(member.user_id) && !isSelf(member.user_id)
            const canRemove = !isOwner(member.user_id) && !isSelf(member.user_id) &&
              !(member.role === 'admin' && adminCount <= 1)

            return (
              <div
                key={member.id}
                className="flex items-center gap-4 px-4 py-3"
              >
                {/* Avatar */}
                <div className="h-10 w-10 rounded-full bg-shizuha-600 flex items-center justify-center text-white font-medium flex-shrink-0">
                  {member.user_name?.[0]?.toUpperCase() || member.user_email?.[0]?.toUpperCase() || '?'}
                </div>

                {/* User info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {member.user_name || 'Unknown User'}
                    {isOwner(member.user_id) && (
                      <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">(Owner)</span>
                    )}
                    {isSelf(member.user_id) && (
                      <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">(You)</span>
                    )}
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400 truncate">
                    {member.user_email}
                  </p>
                </div>

                {/* Role selector */}
                <div className="relative">
                  {canChangeRole ? (
                    <>
                      <button
                        type="button"
                        onClick={() => setOpenDropdown(openDropdown === member.id ? null : member.id)}
                        disabled={isUpdating}
                        className="flex items-center gap-1 px-3 py-1.5 text-sm border border-gray-200 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
                      >
                        <RoleBadge role={member.role} />
                        <ChevronDown className="h-4 w-4 text-gray-400" />
                      </button>

                      {openDropdown === member.id && (
                        <>
                          <div
                            className="fixed inset-0 z-10"
                            onClick={() => setOpenDropdown(null)}
                          />
                          <div className="absolute right-0 top-full mt-1 z-20 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1">
                            {roleOptions.map((option) => (
                              <button
                                key={option.value}
                                onClick={() => handleRoleChange(member.user_id, option.value)}
                                className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-700 ${
                                  member.role === option.value ? 'bg-gray-50 dark:bg-gray-700/50' : ''
                                }`}
                              >
                                <p className="font-medium text-gray-900 dark:text-white">
                                  {option.label}
                                </p>
                                <p className="text-xs text-gray-500 dark:text-gray-400">
                                  {option.description}
                                </p>
                              </button>
                            ))}
                          </div>
                        </>
                      )}
                    </>
                  ) : (
                    <RoleBadge role={member.role} />
                  )}
                </div>

                {/* Remove button */}
                <button
                  type="button"
                  onClick={() => onRemove(member.user_id)}
                  disabled={!canRemove || isUpdating}
                  className={`p-2 rounded-lg transition-colors ${
                    canRemove
                      ? 'text-gray-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20'
                      : 'text-gray-300 dark:text-gray-600 cursor-not-allowed'
                  }`}
                  title={
                    !canRemove
                      ? isOwner(member.user_id)
                        ? 'Cannot remove owner'
                        : isSelf(member.user_id)
                        ? 'Cannot remove yourself'
                        : 'Cannot remove last admin'
                      : 'Remove member'
                  }
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            )
          })}
        </div>
      )}

      <p className="text-xs text-gray-500 dark:text-gray-400">
        <strong>Admin:</strong> Full control | <strong>Editor:</strong> Edit pages | <strong>Viewer:</strong> Read only
      </p>
    </div>
  )
}

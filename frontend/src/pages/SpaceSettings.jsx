import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Settings, Users, Save, Loader2, Plus, ArrowLeft, Trash2 } from 'lucide-react'
import { spacesApi } from '../services/api'
import { useAuth } from '../contexts/AuthContext'
import LoadingSpinner from '../components/LoadingSpinner'
import {
  VisibilitySelector,
  MembersTable,
  AddMemberModal,
  ColorPicker,
} from '../components/settings'

const SPACE_TYPES = [
  { value: 'documentation', label: 'Documentation' },
  { value: 'knowledge_base', label: 'Knowledge Base' },
  { value: 'project', label: 'Project' },
  { value: 'team', label: 'Team' },
  { value: 'personal', label: 'Personal' },
]

export default function SpaceSettings() {
  const { spaceKey } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()

  const [activeTab, setActiveTab] = useState('general')
  const [isAddMemberOpen, setIsAddMemberOpen] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleteConfirmKey, setDeleteConfirmKey] = useState('')

  // Form state for general settings
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    space_type: 'documentation',
    color: '#3B82F6',
    visibility: 'org',
  })
  const [hasChanges, setHasChanges] = useState(false)

  // Fetch space details
  const { data: space, isLoading: spaceLoading, error: spaceError } = useQuery({
    queryKey: ['space', spaceKey],
    queryFn: async () => {
      const response = await spacesApi.get(spaceKey)
      return response.data
    },
  })

  // Fetch members
  const { data: members = [], isLoading: membersLoading } = useQuery({
    queryKey: ['space', spaceKey, 'members'],
    queryFn: async () => {
      const response = await spacesApi.getMembers(spaceKey)
      return response.data
    },
    enabled: !!space,
  })

  // Fetch permissions (handles superusers, owners, and explicit members)
  const { data: permissions, isLoading: permissionsLoading } = useQuery({
    queryKey: ['space', spaceKey, 'permissions'],
    queryFn: async () => {
      const response = await spacesApi.getPermissions(spaceKey)
      return response.data
    },
    enabled: !!space,
  })

  // Initialize form data when space loads
  useEffect(() => {
    if (space) {
      setFormData({
        name: space.name || '',
        description: space.description || '',
        space_type: space.space_type || 'documentation',
        color: space.color || '#3B82F6',
        visibility: space.visibility || 'private',
      })
      setHasChanges(false)
    }
  }, [space])

  // Check if user is admin (via permissions endpoint which handles superusers)
  const isAdmin = permissions && ['owner', 'admin'].includes(permissions.role)

  // Redirect if not admin (wait for permissions to load before deciding)
  useEffect(() => {
    if (space && !spaceLoading && !permissionsLoading && permissions && !isAdmin) {
      navigate(`/spaces/${spaceKey}`, { replace: true })
    }
  }, [space, spaceLoading, permissionsLoading, permissions, isAdmin, spaceKey, navigate])

  // Update space mutation
  const updateSpaceMutation = useMutation({
    mutationFn: (data) => spacesApi.update(spaceKey, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['space', spaceKey] })
      queryClient.invalidateQueries({ queryKey: ['spaces'] })
      setHasChanges(false)
    },
  })

  // Add member mutation
  const addMemberMutation = useMutation({
    mutationFn: ({ userId, role }) => spacesApi.addMember(spaceKey, { user_id: userId, role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['space', spaceKey, 'members'] })
    },
  })

  // Update member role mutation
  const updateRoleMutation = useMutation({
    mutationFn: ({ userId, role }) => spacesApi.updateMemberRole(spaceKey, userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['space', spaceKey, 'members'] })
    },
  })

  // Remove member mutation
  const removeMemberMutation = useMutation({
    mutationFn: (userId) => spacesApi.removeMember(spaceKey, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['space', spaceKey, 'members'] })
    },
  })

  // Delete space mutation
  const deleteSpaceMutation = useMutation({
    mutationFn: () => spacesApi.delete(spaceKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['spaces'] })
      navigate('/spaces', { replace: true })
    },
  })

  const handleInputChange = (field, value) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
    setHasChanges(true)
  }

  const handleSave = () => {
    updateSpaceMutation.mutate(formData)
  }

  const handleAddMember = async (userId, role) => {
    await addMemberMutation.mutateAsync({ userId, role })
  }

  const handleRoleChange = (userId, role) => {
    updateRoleMutation.mutate({ userId, role })
  }

  const handleRemoveMember = (userId) => {
    if (confirm('Are you sure you want to remove this member?')) {
      removeMemberMutation.mutate(userId)
    }
  }

  if (spaceLoading || permissionsLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (spaceError || !space) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Space not found</h2>
        <Link to="/spaces" className="text-shizuha-600 hover:underline mt-2 inline-block">
          Back to spaces
        </Link>
      </div>
    )
  }

  if (!isAdmin) {
    return null // Will redirect
  }

  return (
    <div className="max-w-4xl mx-auto">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-6">
        <Link to="/spaces" className="hover:text-gray-700 dark:hover:text-gray-300">
          Spaces
        </Link>
        <ChevronRight className="h-4 w-4" />
        <Link
          to={`/spaces/${spaceKey}`}
          className="hover:text-gray-700 dark:hover:text-gray-300"
        >
          {space.name}
        </Link>
        <ChevronRight className="h-4 w-4" />
        <span className="text-gray-900 dark:text-white">Settings</span>
      </nav>

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Link
            to={`/spaces/${spaceKey}`}
            className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
              <Settings className="h-6 w-6" />
              Space Settings
            </h1>
            <p className="text-gray-500 dark:text-gray-400">{space.key}</p>
          </div>
        </div>

        {activeTab === 'general' && hasChanges && (
          <button
            onClick={handleSave}
            disabled={updateSpaceMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 disabled:opacity-50 transition-colors"
          >
            {updateSpaceMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save Changes
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-700 mb-6">
        <nav className="flex gap-6">
          <button
            onClick={() => setActiveTab('general')}
            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'general'
                ? 'border-shizuha-600 text-shizuha-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <Settings className="h-4 w-4 inline-block mr-2" />
            General
          </button>
          <button
            onClick={() => setActiveTab('access')}
            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'access'
                ? 'border-shizuha-600 text-shizuha-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <Users className="h-4 w-4 inline-block mr-2" />
            Access
          </button>
        </nav>
      </div>

      {/* Tab content */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
        {activeTab === 'general' && (
          <div className="space-y-6">
            {/* Space Key (read-only) */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Space Key
              </label>
              <input
                type="text"
                value={space.key}
                disabled
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 cursor-not-allowed"
              />
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                The space key cannot be changed after creation.
              </p>
            </div>

            {/* Name */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Name
              </label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => handleInputChange('name', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-shizuha-500 focus:border-transparent"
                placeholder="Space name"
              />
            </div>

            {/* Description */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Description
              </label>
              <textarea
                value={formData.description}
                onChange={(e) => handleInputChange('description', e.target.value)}
                rows={3}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-shizuha-500 focus:border-transparent resize-none"
                placeholder="Describe the purpose of this space..."
              />
            </div>

            {/* Space Type */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Space Type
              </label>
              <select
                value={formData.space_type}
                onChange={(e) => handleInputChange('space_type', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-shizuha-500 focus:border-transparent"
              >
                {SPACE_TYPES.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Color Picker */}
            <ColorPicker
              value={formData.color}
              onChange={(color) => handleInputChange('color', color)}
            />

            {/* Error message */}
            {updateSpaceMutation.isError && (
              <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400 text-sm">
                Failed to save changes. Please try again.
              </div>
            )}

            {/* Success message */}
            {updateSpaceMutation.isSuccess && !hasChanges && (
              <div className="p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg text-green-700 dark:text-green-400 text-sm">
                Changes saved successfully.
              </div>
            )}

            {/* Danger Zone */}
            <div className="mt-8 pt-6 border-t border-red-200 dark:border-red-800">
              <h3 className="text-lg font-medium text-red-600 dark:text-red-400 mb-2">Danger Zone</h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                Deleting a space is permanent and cannot be undone. All pages, attachments, and version history within this space will be permanently removed.
              </p>
              <button
                onClick={() => setShowDeleteConfirm(true)}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                <Trash2 className="h-4 w-4" />
                Delete Space
              </button>
            </div>
          </div>
        )}

        {activeTab === 'access' && (
          <div className="space-y-6">
            {/* Visibility Selector */}
            <VisibilitySelector
              value={formData.visibility}
              onChange={(visibility) => {
                handleInputChange('visibility', visibility)
                // Auto-save visibility changes
                updateSpaceMutation.mutate({ visibility })
              }}
              disabled={updateSpaceMutation.isPending}
            />

            <hr className="border-gray-200 dark:border-gray-700" />

            {/* Members section */}
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-medium text-gray-900 dark:text-white">Members</h3>
              <button
                onClick={() => setIsAddMemberOpen(true)}
                className="flex items-center gap-2 px-3 py-1.5 text-sm bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 transition-colors"
              >
                <Plus className="h-4 w-4" />
                Add Member
              </button>
            </div>

            {membersLoading ? (
              <div className="flex justify-center py-8">
                <LoadingSpinner />
              </div>
            ) : (
              <MembersTable
                members={members}
                currentUserId={user?.id}
                ownerId={space.owner_id}
                onRoleChange={handleRoleChange}
                onRemove={handleRemoveMember}
                isUpdating={updateRoleMutation.isPending || removeMemberMutation.isPending}
              />
            )}
          </div>
        )}
      </div>

      {/* Add Member Modal */}
      <AddMemberModal
        isOpen={isAddMemberOpen}
        onClose={() => setIsAddMemberOpen(false)}
        spaceKey={spaceKey}
        onAdd={handleAddMember}
      />

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md p-6">
            <h2 className="text-lg font-semibold text-red-600 dark:text-red-400 mb-2">
              Delete Space
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              This action <strong>cannot be undone</strong>. This will permanently delete the{' '}
              <strong>{space.name}</strong> space, all its pages, attachments, and version history.
            </p>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
              Please type <strong>{space.key}</strong> to confirm.
            </p>
            <input
              type="text"
              value={deleteConfirmKey}
              onChange={(e) => setDeleteConfirmKey(e.target.value)}
              placeholder={space.key}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-red-500 focus:border-transparent mb-4"
            />
            {deleteSpaceMutation.isError && (
              <div className="p-3 mb-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400 text-sm">
                Failed to delete space. Please try again.
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => {
                  setShowDeleteConfirm(false)
                  setDeleteConfirmKey('')
                }}
                className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteSpaceMutation.mutate()}
                disabled={deleteConfirmKey !== space.key || deleteSpaceMutation.isPending}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {deleteSpaceMutation.isPending ? 'Deleting...' : 'Delete this space'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { spacesApi, labelsApi } from '../services/api'
import { useAuth } from './AuthContext'

const SpaceContext = createContext(null)

const CURRENT_SPACE_KEY = 'shizuha_current_space'

const organizationSpaceStorageKey = (organizationId) => (
  organizationId ? `${CURRENT_SPACE_KEY}:${organizationId}` : null
)

export function SpaceProvider({ children }) {
  const { isAuthenticated, isLoading: authLoading, organization } = useAuth()
  const queryClient = useQueryClient()
  const [currentSpaceKey, setCurrentSpaceKey] = useState(null)
  const organizationId = organization?.id
  const currentSpaceStorageKey = organizationSpaceStorageKey(organizationId)

  // Fetch spaces
  const { data: spaces = [], isLoading: spacesLoading } = useQuery({
    queryKey: ['spaces', organizationId],
    queryFn: async () => {
      const response = await spacesApi.list()
      return response.data.results || response.data
    },
    enabled: isAuthenticated && !authLoading && Boolean(organizationId),
  })

  // Get current space
  const currentSpace = spaces.find(s => s.key === currentSpaceKey) || spaces[0]

  // Fetch labels
  const { data: labels = [], isLoading: labelsLoading } = useQuery({
    queryKey: ['labels', organizationId],
    queryFn: async () => {
      const response = await labelsApi.list()
      return response.data.results || response.data
    },
    enabled: isAuthenticated && !authLoading && Boolean(organizationId),
  })

  // A space selection belongs to one organization. Restore only that
  // organization's prior selection when its authenticated context is ready.
  useEffect(() => {
    setCurrentSpaceKey(
      currentSpaceStorageKey
        ? localStorage.getItem(currentSpaceStorageKey) || null
        : null
    )
  }, [currentSpaceStorageKey])

  // Update current space when this organization's spaces load. A stale key
  // from another tenant is never retained or displayed.
  useEffect(() => {
    if (spaces.length === 0) {
      setCurrentSpaceKey(null)
    } else if (!spaces.some(space => space.key === currentSpaceKey)) {
      setCurrentSpaceKey(spaces[0].key)
    }
  }, [spaces, currentSpaceKey])

  // Persist current space
  useEffect(() => {
    if (currentSpaceStorageKey && currentSpaceKey) {
      localStorage.setItem(currentSpaceStorageKey, currentSpaceKey)
    }
  }, [currentSpaceKey, currentSpaceStorageKey])

  const switchSpace = useCallback((key) => {
    setCurrentSpaceKey(key)
    queryClient.invalidateQueries({ queryKey: ['pages'] })
  }, [queryClient])

  // Create space mutation
  const createSpaceMutation = useMutation({
    mutationFn: (data) => spacesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['spaces'] })
    },
  })

  const value = {
    spaces,
    currentSpace,
    currentSpaceKey,
    switchSpace,
    createSpace: createSpaceMutation.mutateAsync,
    spacesLoading,
    labels,
    labelsLoading,
    isLoading: spacesLoading || labelsLoading,
  }

  return <SpaceContext.Provider value={value}>{children}</SpaceContext.Provider>
}

export function useSpace() {
  const context = useContext(SpaceContext)
  if (!context) {
    throw new Error('useSpace must be used within a SpaceProvider')
  }
  return context
}

export default SpaceContext

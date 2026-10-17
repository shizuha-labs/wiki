import { Globe, Lock, Building2 } from 'lucide-react'

const visibilityOptions = [
  {
    value: 'private',
    label: 'Private',
    description: 'Only explicitly added members can view',
    icon: Lock,
  },
  {
    value: 'org',
    label: 'Organization',
    description: 'All members of the organization can view',
    icon: Building2,
  },
  {
    value: 'public',
    label: 'Public',
    description: 'Anyone on the internet can view, even without signing in',
    icon: Globe,
  },
]

export default function VisibilitySelector({ value, onChange, disabled = false }) {
  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
        Space Visibility
      </label>
      <div className="space-y-2">
        {visibilityOptions.map((option) => {
          const Icon = option.icon
          const isSelected = value === option.value

          return (
            <label
              key={option.value}
              className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                isSelected
                  ? 'border-shizuha-500 bg-shizuha-50 dark:bg-shizuha-900/20'
                  : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
              } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <input
                type="radio"
                name="visibility"
                value={option.value}
                checked={isSelected}
                onChange={(e) => onChange(e.target.value)}
                disabled={disabled}
                className="sr-only"
              />
              <div className={`mt-0.5 ${isSelected ? 'text-shizuha-600' : 'text-gray-400'}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="flex-1 min-w-0">
                <p className={`text-sm font-medium ${isSelected ? 'text-shizuha-700 dark:text-shizuha-300' : 'text-gray-900 dark:text-white'}`}>
                  {option.label}
                </p>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {option.description}
                </p>
              </div>
              <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                isSelected
                  ? 'border-shizuha-600 bg-shizuha-600'
                  : 'border-gray-300 dark:border-gray-600'
              }`}>
                {isSelected && (
                  <div className="w-1.5 h-1.5 rounded-full bg-white" />
                )}
              </div>
            </label>
          )
        })}
      </div>
    </div>
  )
}

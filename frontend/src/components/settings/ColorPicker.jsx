const presetColors = [
  '#3B82F6', // blue
  '#8B5CF6', // purple
  '#EC4899', // pink
  '#EF4444', // red
  '#F97316', // orange
  '#EAB308', // yellow
  '#22C55E', // green
  '#14B8A6', // teal
  '#06B6D4', // cyan
  '#6366F1', // indigo
  '#64748B', // slate
  '#78716C', // stone
]

export default function ColorPicker({ value, onChange, disabled = false }) {
  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
        Space Color
      </label>
      <div className="flex flex-wrap gap-2">
        {presetColors.map((color) => (
          <button
            key={color}
            type="button"
            onClick={() => onChange(color)}
            disabled={disabled}
            className={`w-8 h-8 rounded-lg transition-all ${
              value === color
                ? 'ring-2 ring-offset-2 ring-shizuha-500 dark:ring-offset-gray-800'
                : 'hover:scale-110'
            } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
            style={{ backgroundColor: color }}
            title={color}
          />
        ))}
      </div>
      <div className="flex items-center gap-2">
        <label className="text-sm text-gray-500 dark:text-gray-400">Custom:</label>
        <input
          type="color"
          value={value || '#3B82F6'}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          className="h-8 w-16 cursor-pointer rounded border border-gray-300 dark:border-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
        />
        <span className="text-sm text-gray-500 dark:text-gray-400 font-mono">
          {value || '#3B82F6'}
        </span>
      </div>
    </div>
  )
}

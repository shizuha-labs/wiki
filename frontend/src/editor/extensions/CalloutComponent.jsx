import { NodeViewContent, NodeViewWrapper } from '@tiptap/react'
import { Info, FileText, Lightbulb, AlertTriangle, XCircle } from 'lucide-react'
import { CALLOUT_TYPES } from './Callout'

const ICONS = {
  info: Info,
  note: FileText,
  tip: Lightbulb,
  warning: AlertTriangle,
  error: XCircle,
}

export default function CalloutComponent({ node, updateAttributes }) {
  const type = node.attrs.type || 'info'
  const config = CALLOUT_TYPES[type] || CALLOUT_TYPES.info
  const Icon = ICONS[type] || Info

  return (
    <NodeViewWrapper className="callout-wrapper">
      <div
        className={`callout callout-${type} ${config.bgClass} border-l-4 ${config.borderClass} rounded-r-lg p-4 my-4`}
        data-callout=""
        data-callout-type={type}
      >
        <div className="flex gap-3">
          <div className={`flex-shrink-0 mt-0.5 ${config.iconClass}`}>
            <Icon className="h-5 w-5" />
          </div>
          <div className="flex-1 min-w-0 callout-content">
            <NodeViewContent />
          </div>
        </div>
      </div>
    </NodeViewWrapper>
  )
}

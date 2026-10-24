import { BadgeCheck, CircleDashed } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

/**
 * WIKI-126 (Slice A4): verification badge + staleness display.
 *
 * SCS-239 contract: the SERVER omits `verified`/`verified_at` for
 * unauthenticated callers — so `verified === undefined` means "no
 * verification metadata was sent" (anonymous path) and renders NOTHING.
 * The badge never fabricates state the API did not send.
 *
 * - verified === true  → green "Verified <n>d ago" (staleness from verified_at)
 * - verified === false → gray "Unverified" (+ optional last-change date)
 * - verified === undefined → render nothing (anonymous caller)
 */
export function VerificationBadge({ verified, verifiedAt, updatedAt, compact = false }) {
  if (verified === undefined) return null

  if (verified) {
    const staleness = verifiedAt
      ? `Verified ${formatDistanceToNow(new Date(verifiedAt), { addSuffix: true })}`
      : 'Verified'
    return (
      <span
        title={staleness}
        className={`inline-flex items-center gap-1 rounded-full bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 ${
          compact ? 'text-[10px] px-1.5 py-0.5' : 'text-xs px-2 py-0.5'
        }`}
      >
        <BadgeCheck className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />
        {!compact && staleness}
      </span>
    )
  }

  return (
    <span
      title={updatedAt ? `Unverified · last changed ${formatDistanceToNow(new Date(updatedAt), { addSuffix: true })}` : 'Unverified'}
      className={`inline-flex items-center gap-1 rounded-full bg-gray-100 dark:bg-gray-700/60 text-gray-500 dark:text-gray-400 ${
        compact ? 'text-[10px] px-1.5 py-0.5' : 'text-xs px-2 py-0.5'
      }`}
    >
      <CircleDashed className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />
      {!compact && 'Unverified'}
    </span>
  )
}

/**
 * Staleness display math (WIKI-126 tests): "Verified 12d ago" derives from
 * verified_at; unverified pages show "Unverified" with the last-change date.
 * Exported pure so the rule is unit-testable without a DOM.
 */
export function stalenessLabel(verified, verifiedAt, updatedAt) {
  if (verified === undefined) return null
  if (verified && verifiedAt) {
    return `Verified ${formatDistanceToNow(new Date(verifiedAt), { addSuffix: true })}`
  }
  if (!verified && updatedAt) {
    return `Unverified · changed ${formatDistanceToNow(new Date(updatedAt), { addSuffix: true })}`
  }
  return verified ? 'Verified' : 'Unverified'
}

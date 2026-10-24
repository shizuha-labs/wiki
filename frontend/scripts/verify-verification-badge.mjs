import assert from 'node:assert/strict'

// WIKI-126 (Slice A4): staleness display math for the verification badge.
// Dep-free mirror of the rule in frontend/src/components/VerificationBadge.jsx
// (repo verify-script convention: node built-ins only — the component itself
// is compile-checked by the vite build and reviewed on the PR). The RULE
// pinned here: which bucket the label picks for each input shape.

const DAY = 24 * 60 * 60 * 1000
const MIN = 60 * 1000
const now = new Date()
const iso = (msAgo) => new Date(now.getTime() - msAgo).toISOString()

// Dep-free stand-in for date-fns formatDistanceToNow over the buckets the
// design's examples use ("Verified 12d ago").
function distance(ms) {
  if (ms < MIN) return 'less than a minute ago'
  if (ms < 60 * MIN) return `${Math.round(ms / MIN)} minutes ago`
  if (ms < DAY) return `${Math.round(ms / (60 * MIN))} hours ago`
  const days = Math.round(ms / DAY)
  return days === 1 ? '1 day ago' : `${days} days ago`
}

function stalenessLabel(verified, verifiedAt, updatedAt) {
  if (verified === undefined) return null // SCS-239: anonymous path renders nothing
  if (verified && verifiedAt) {
    return `Verified ${distance(now.getTime() - new Date(verifiedAt).getTime())}`
  }
  if (!verified && updatedAt) {
    return `Unverified · changed ${distance(now.getTime() - new Date(updatedAt).getTime())}`
  }
  return verified ? 'Verified' : 'Unverified'
}

// Authenticated + verified → staleness derives from verified_at (12d case).
assert.match(stalenessLabel(true, iso(12 * DAY), iso(DAY)), /^Verified 12 days ago$/)

// Authenticated + verified just now (minutes bucket).
assert.match(stalenessLabel(true, iso(5 * MIN)), /^Verified 5 minutes ago$/)

// Authenticated + unverified → "Unverified" with last-change date.
assert.match(stalenessLabel(false, null, iso(3 * DAY)), /^Unverified · changed 3 days ago$/)

// Unverified with NO last-change date → bare label.
assert.equal(stalenessLabel(false, null, null), 'Unverified')

// ANONYMOUS PATH (SCS-239): the server OMITS the fields — `verified ===
// undefined` renders NOTHING, never a fabricated state, even when other
// timestamps are present.
assert.equal(stalenessLabel(undefined, null, null), null)
assert.equal(stalenessLabel(undefined, iso(DAY), iso(DAY)), null)

console.log('verify-verification-badge: all staleness display assertions passed')

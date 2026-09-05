import type { Confidence } from '../types'

const LABEL: Record<Confidence, string> = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence',
  'n/a': 'Confidence n/a',
}

// Low gets its own tone. Sharing the warning colour made "medium" and "low"
// visually identical, which defeats the point of grading confidence at all.
const TONE: Record<Confidence, 'info' | 'warn' | 'error' | 'muted'> = {
  high: 'info',
  medium: 'warn',
  low: 'error',
  'n/a': 'muted',
}

export function ConfidenceBadge({ level }: { level: Confidence }) {
  const tone = TONE[level]
  return (
    <span className={`confidence-badge confidence-badge--${tone}`}>
      {LABEL[level]}
    </span>
  )
}

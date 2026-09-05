import type { Confidence } from '../types'

const LABEL: Record<Confidence, string> = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence',
  'n/a': 'Confidence n/a',
}

const TONE: Record<Confidence, 'info' | 'warn' | 'muted'> = {
  high: 'info',
  medium: 'warn',
  low: 'warn',
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

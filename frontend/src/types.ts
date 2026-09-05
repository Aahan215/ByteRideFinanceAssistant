// THE CONTRACT between this frontend and app/api.py.
// Mirrors the Answer pydantic model. If the API changes, change this first --
// everything else is written against these types.

export type Confidence = 'high' | 'medium' | 'low' | 'n/a'

export interface ComparisonRow {
  [dimension: string]: string | number | null
  value: number | null
  previous: number | null
  delta: number | null
  delta_pct: number | null
}

export interface Comparison {
  window: string
  value: number | null
  previous: number | null
  delta: number | null
  delta_pct: number | null
  rows: ComparisonRow[]
}

export type Row = Record<string, string | number | null>

export interface Answer {
  answer: string
  confidence: Confidence
  sql: string | null
  window: string | null
  breakdown: Row[]
  evidence: Row[]
  comparison: Comparison | null
  /** Unusual amounts spotted while answering the original question. */
  anomalies: string[]
  /** Why the confidence badge says what it says. Never show a bare badge. */
  confidence_reasons: string[]
  warnings: string[]
  refused: boolean
  /** The QuerySpec that actually ran. Powers export and "show your working". */
  spec: Record<string, unknown> | null
}

export interface Health {
  ok: boolean
  /** The assistant's "today". See `anchor.mode` in the semantic layer. */
  anchor_date: string
  /** "data" (latest transaction) or "wall_clock" (the real date). */
  mode?: 'data' | 'wall_clock'
  data_latest?: string
  /** True when the anchor is ahead of the data, so relative dates match nothing. */
  stale?: boolean
  warning?: string | null
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  text?: string
  answer?: Answer
  pending?: boolean
  error?: string
}

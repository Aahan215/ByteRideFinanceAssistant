import type { Answer, Health, ScopeOption, Scopes } from './types'

const json = { 'Content-Type': 'application/json' }

export async function health(): Promise<Health> {
  const r = await fetch('/health')
  if (!r.ok) throw new Error(`health ${r.status}`)
  return r.json()
}

export async function scopes(): Promise<Scopes> {
  const r = await fetch('/scopes')
  if (!r.ok) throw new Error(`scopes ${r.status}`)
  return r.json()
}

export async function ask(
  question: string, sessionId: string, scope: ScopeOption,
): Promise<Answer> {
  const r = await fetch('/ask', {
    method: 'POST',
    headers: json,
    body: JSON.stringify({
      question, session_id: sessionId,
      scope_level: scope.level, scope_value: scope.value ?? null,
    }),
  })
  if (!r.ok) throw new Error(`ask failed: ${r.status} ${await r.text()}`)
  return r.json()
}

/** Runs the full pipeline from a hand-written spec, with no model in the loop. */
export async function askSpec(spec: Record<string, unknown>): Promise<Answer> {
  const r = await fetch('/ask_spec', { method: 'POST', headers: json, body: JSON.stringify(spec) })
  if (!r.ok) throw new Error(`ask_spec failed: ${r.status}`)
  return r.json()
}

export async function exportFile(spec: Record<string, unknown>, fmt: 'csv' | 'xlsx') {
  const r = await fetch(`/export?fmt=${fmt}`, { method: 'POST', headers: json, body: JSON.stringify(spec) })
  if (!r.ok) throw new Error(`export failed: ${r.status}`)
  const blob = await r.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `breakdown.${fmt}`
  a.click()
  URL.revokeObjectURL(a.href)
}

/** Amounts are INR. Indian digit grouping, matching what the backend narrates. */
export const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency', currency: 'INR', maximumFractionDigits: 0,
})

export const AMOUNT_KEY = /amount|value|previous|delta|balance/i

const MONTH_FMT = new Intl.DateTimeFormat('en-IN', { month: 'long', year: 'numeric' })

export function formatCell(key: string, v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') {
    if (/pct/i.test(key)) return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`
    return AMOUNT_KEY.test(key) ? inr.format(v) : v.toLocaleString('en-IN')
  }
  const s = String(v)
  // A trend groups by month or quarter; those arrive as timestamps and must
  // not be shown as "2026-04-01T00:00:00" on a chart axis or in a table.
  if (/^(month|quarter)$/i.test(key) && /^\d{4}-\d{2}/.test(s)) {
    const d = new Date(s)
    if (!Number.isNaN(d.valueOf())) {
      return /quarter/i.test(key)
        ? `Q${Math.floor(d.getMonth() / 3) + 1} ${d.getFullYear()}`
        : MONTH_FMT.format(d)
    }
  }
  if (/date/i.test(key) && /^\d{4}-\d{2}/.test(s)) return s.slice(0, 19).replace('T', ' ')
  return s
}

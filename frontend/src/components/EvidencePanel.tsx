import type { Answer } from '../types'
import { BreakdownTable } from './BreakdownTable'
import './tables.css'

const PREVIEW_ROWS = 8

export function EvidencePanel({ answer }: { answer: Answer }) {
  if (answer.sql === null) return null

  const preview = answer.evidence.slice(0, PREVIEW_ROWS)

  return (
    <details className="evidence-panel">
      <summary>Show the query and the source records</summary>
      <div className="evidence-body">
        <pre className="sql-pre">{answer.sql}</pre>
        <span className="evidence-chip">
          {answer.evidence.length} source records (account numbers and UTRs masked)
        </span>
        <BreakdownTable rows={preview} />
      </div>
    </details>
  )
}

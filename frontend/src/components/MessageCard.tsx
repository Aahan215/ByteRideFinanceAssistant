import { useCallback, useState } from 'react'
import type { Message } from '../types'
import { exportFile } from '../api'
import { ConfidenceBadge } from './ConfidenceBadge'
// These siblings are written by another agent against the contract noted below.
import { BreakdownTable } from './BreakdownTable'       // ({ rows }: { rows: Row[] })
import { ComparisonTable } from './ComparisonTable'     // ({ comparison }: { comparison: Comparison })
import { EvidencePanel } from './EvidencePanel'         // ({ answer }: { answer: Answer })
import { AnswerChart } from './Charts'                  // ({ answer }: { answer: Answer })
import './chat.css'

export function MessageCard({ message }: { message: Message }) {
  if (message.role === 'user') {
    return (
      <div className="msg-row msg-row--user">
        <div className="bubble bubble--user">{message.text}</div>
      </div>
    )
  }

  if (message.pending) {
    return (
      <div className="msg-row msg-row--assistant">
        <div className="bubble bubble--pending">
          <span className="pending-dot" aria-hidden="true" />
          Querying your transactions…
        </div>
      </div>
    )
  }

  if (message.error) {
    return (
      <div className="msg-row msg-row--assistant">
        <div className="bubble bubble--notice">{message.error}</div>
      </div>
    )
  }

  const { answer } = message
  if (!answer) return null

  const skipBreakdown =
    answer.breakdown.length === 1 && Object.keys(answer.breakdown[0]).length === 1
  const showComparison = Boolean(answer.comparison?.rows?.length)

  return (
    <div className="msg-row msg-row--assistant">
      <div className={`bubble bubble--answer${answer.refused ? ' bubble--refused' : ''}`}>
        <p className="answer-text">{answer.answer}</p>

        <div className="meta-row">
          {answer.window && <span className="window-chip">{answer.window}</span>}
          <ConfidenceBadge level={answer.confidence} />
        </div>

        {answer.confidence_reasons.length > 0 && (
          <ul className="confidence-reasons">
            {answer.confidence_reasons.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        )}

        {answer.anomalies.map((a, i) => (
          <div key={i} className="callout callout--anomaly">
            <strong>Unusual:</strong> {a}
          </div>
        ))}

        {answer.warnings.map((w, i) => (
          <div key={i} className="callout callout--warning">
            {w}
          </div>
        ))}

        <AnswerChart answer={answer} />

        {showComparison ? (
          <ComparisonTable comparison={answer.comparison!} />
        ) : (
          !skipBreakdown && <BreakdownTable rows={answer.breakdown} />
        )}

        <EvidencePanel answer={answer} />

        {!answer.refused && answer.spec && <ExportButtons spec={answer.spec} />}
      </div>
    </div>
  )
}

function ExportButtons({ spec }: { spec: Record<string, unknown> }) {
  const [busy, setBusy] = useState<'csv' | 'xlsx' | null>(null)

  const doExport = useCallback(async (fmt: 'csv' | 'xlsx') => {
    setBusy(fmt)
    try {
      await exportFile(spec, fmt)
    } finally {
      setBusy(null)
    }
  }, [spec])

  return (
    <div className="export-row">
      <button
        type="button"
        className="export-btn"
        disabled={busy !== null}
        onClick={() => doExport('csv')}
      >
        {busy === 'csv' ? 'Exporting…' : 'Export CSV'}
      </button>
      <button
        type="button"
        className="export-btn"
        disabled={busy !== null}
        onClick={() => doExport('xlsx')}
      >
        {busy === 'xlsx' ? 'Exporting…' : 'Export Excel'}
      </button>
    </div>
  )
}

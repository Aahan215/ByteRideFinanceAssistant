import { useCallback, useState } from 'react'

const SUGGESTIONS = [
  'Where did I spend the most this month?',
  'Total tax I paid in the last 3 months',
  'Break my spending down by category',
  'How does that compare to the month before?',
  'Which transactions are unreconciled?',
]

export function Composer({ onSend, busy }: { onSend: (q: string) => void; busy: boolean }) {
  const [text, setText] = useState('')

  const submit = useCallback((q: string) => {
    const trimmed = q.trim()
    if (!trimmed || busy) return
    onSend(trimmed)
    setText('')
  }, [busy, onSend])

  return (
    <div className="composer">
      <div className="composer-suggestions">
        {SUGGESTIONS.map(s => (
          <button
            key={s}
            type="button"
            className="suggestion-chip"
            disabled={busy}
            onClick={() => submit(s)}
          >
            {s}
          </button>
        ))}
      </div>
      <form
        className="composer-row"
        onSubmit={e => { e.preventDefault(); submit(text) }}
      >
        <input
          type="text"
          className="composer-input"
          placeholder="Ask about your transactions…"
          value={text}
          disabled={busy}
          onChange={e => setText(e.target.value)}
        />
        <button type="submit" className="composer-ask" disabled={busy || !text.trim()}>
          Ask
        </button>
      </form>
    </div>
  )
}

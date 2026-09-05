import { useCallback, useEffect, useRef, useState } from 'react'
import { ask, health } from './api'
import type { Health, Message, ScopeOption } from './types'
import { MessageCard } from './components/MessageCard'
import { Composer } from './components/Composer'
import { ScopePicker } from './components/ScopePicker'
import './App.css'

const SESSION = Math.random().toString(36).slice(2)

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [meta, setMeta] = useState<Health | null>(null)
  const [busy, setBusy] = useState(false)
  const [scope, setScope] = useState<ScopeOption>(
    { level: 'all', label: 'All accounts', txns: 0 })
  const feedRef = useRef<HTMLDivElement>(null)

  useEffect(() => { health().then(setMeta).catch(() => setMeta(null)) }, [])
  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const send = useCallback(async (question: string) => {
    const id = crypto.randomUUID()
    setMessages(m => [...m,
      { id: `${id}-q`, role: 'user', text: question },
      { id, role: 'assistant', pending: true }])
    setBusy(true)
    try {
      const answer = await ask(question, SESSION, scope)
      setMessages(m => m.map(x => x.id === id ? { ...x, pending: false, answer } : x))
    } catch (e) {
      const error = e instanceof Error ? e.message : String(e)
      setMessages(m => m.map(x => x.id === id ? { ...x, pending: false, error } : x))
    } finally {
      setBusy(false)
    }
  }, [scope])

  // The assistant's "today" is the latest date in the DATA. Saying so up front
  // stops anyone reading "this month" as the wall-clock month.
  const anchor = meta && new Date(meta.anchor_date + 'T00:00:00')

  return (
    <div className="app">
      <header className="topbar">
        <h1>Finance Assistant</h1>
        {anchor ? (
          <span className="anchor">
            Data through <b>{anchor.toLocaleDateString('en-IN',
              { day: 'numeric', month: 'short', year: 'numeric' })}</b>
            {' — '}“this month” means {anchor.toLocaleDateString('en-IN',
              { month: 'long', year: 'numeric' })}
          </span>
        ) : <span className="anchor">backend unreachable</span>}
        <ScopePicker
          value={scope}
          onChange={s => {
            // A follow-up refining the previous scope's question would be
            // nonsense, so the transcript starts clean.
            setScope(s)
            setMessages([])
          }}
        />
        {meta?.stale && meta.warning && (
          <span className="anchor-warning" role="alert">{meta.warning}</span>
        )}
      </header>

      <div className="feed" ref={feedRef}>
        {messages.length === 0 && (
          <div className="empty">
            <h2>Ask about your spending</h2>
            <p>Every answer is computed by SQL against your transactions.
               You can open the query and the source records behind any number.</p>
          </div>
        )}
        {messages.map(m => <MessageCard key={m.id} message={m} />)}
      </div>

      <Composer onSend={send} busy={busy} />
    </div>
  )
}

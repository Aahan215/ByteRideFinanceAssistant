import { useEffect, useState } from 'react'
import { scopes as fetchScopes } from '../api'
import type { ScopeOption, Scopes } from '../types'
import './scope.css'

/** Who the assistant answers for. A selector, not authentication -- but every
 *  query is constrained to the choice, so one account cannot see another's
 *  transactions. Changing it starts a fresh conversation. */
export function ScopePicker(
  { value, onChange }: { value: ScopeOption; onChange: (s: ScopeOption) => void },
) {
  const [all, setAll] = useState<Scopes | null>(null)

  useEffect(() => { fetchScopes().then(setAll).catch(() => setAll(null)) }, [])
  if (!all) return null

  const options: ScopeOption[] = [all.all, ...all.entities, ...all.accounts]
  const key = (s: ScopeOption) => `${s.level}:${s.value ?? ''}`

  return (
    <label className="scope">
      <span className="scope-label">Viewing</span>
      <select
        value={key(value)}
        onChange={e => {
          const next = options.find(o => key(o) === e.target.value)
          if (next) onChange(next)
        }}
      >
        <option value="all:">{all.all.label} ({all.all.txns.toLocaleString('en-IN')})</option>
        {all.entities.length > 0 && (
          <optgroup label="Entities">
            {all.entities.map(e => (
              <option key={key(e)} value={key(e)}>
                {e.label} — {e.txns.toLocaleString('en-IN')}
              </option>
            ))}
          </optgroup>
        )}
        {all.accounts.length > 0 && (
          <optgroup label="Accounts">
            {all.accounts.map(a => (
              <option key={key(a)} value={key(a)}>
                {a.label} — {a.txns.toLocaleString('en-IN')}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </label>
  )
}

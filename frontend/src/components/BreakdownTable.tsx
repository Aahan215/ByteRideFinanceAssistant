import { AMOUNT_KEY, formatCell } from '../api'
import type { Row } from '../types'
import './tables.css'

const MAX_ROWS = 12

function labelFor(key: string): string {
  return key.replace(/_/g, ' ').toUpperCase()
}

export function BreakdownTable({ rows }: { rows: Row[] }) {
  if (rows.length === 0) return null

  const columns = Object.keys(rows[0])
  const visible = rows.slice(0, MAX_ROWS)
  const extra = rows.length - visible.length

  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col} className={AMOUNT_KEY.test(col) ? 'num' : undefined}>
                {labelFor(col)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((row, i) => (
            <tr key={i}>
              {columns.map((col) => (
                <td key={col} className={AMOUNT_KEY.test(col) ? 'num' : undefined}>
                  {formatCell(col, row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {extra > 0 && <span className="more-rows-chip">+{extra} more rows</span>}
    </div>
  )
}

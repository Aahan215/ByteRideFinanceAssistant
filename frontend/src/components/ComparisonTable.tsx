import { formatCell } from '../api'
import type { Comparison, ComparisonRow } from '../types'
import './tables.css'

const FIXED_KEYS = ['value', 'previous', 'delta', 'delta_pct']

function dimensionKeyOf(row: ComparisonRow): string {
  return Object.keys(row).find((k) => !FIXED_KEYS.includes(k)) ?? ''
}

function labelFor(key: string): string {
  return key.replace(/_/g, ' ').toUpperCase()
}

function deltaClass(v: number | null): string | undefined {
  if (v === null) return undefined
  if (v > 0) return 'delta-pos'
  if (v < 0) return 'delta-neg'
  return undefined
}

export function ComparisonTable({ comparison }: { comparison: Comparison }) {
  const { rows } = comparison
  if (rows.length === 0) return null

  const dimKey = dimensionKeyOf(rows[0])

  return (
    <div className="table-scroll">
      <table className="data-table comparison-table">
        <caption>vs {comparison.window}</caption>
        <thead>
          <tr>
            <th>{labelFor(dimKey || 'dimension')}</th>
            <th className="num">THIS PERIOD</th>
            <th className="num">PREVIOUS</th>
            <th className="num">DELTA</th>
            <th className="num">DELTA %</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const gone = row.value === 0 && (row.previous ?? 0) > 0
            return (
              <tr key={i} className={gone ? 'row-gone' : undefined}>
                <td>{formatCell(dimKey, row[dimKey])}</td>
                <td className="num">
                  {formatCell('value', row.value)}
                  {gone && <span className="gone-tag">gone</span>}
                </td>
                <td className="num">{formatCell('previous', row.previous)}</td>
                <td className={`num ${deltaClass(row.delta) ?? ''}`.trim()}>
                  {formatCell('delta', row.delta)}
                </td>
                <td className={`num ${deltaClass(row.delta_pct) ?? ''}`.trim()}>
                  {formatCell('delta_pct', row.delta_pct)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

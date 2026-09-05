import { useEffect, useMemo, useState } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'
import type { Answer } from '../types'
import { inr } from '../api'
import './charts.css'

type Row = Record<string, string | number | null>

interface ThemeVars {
  colors: string[]
  line: string
  muted: string
  ink: string
}

const FALLBACK_COLORS = ['#1f6feb', '#12805c', '#b0721a', '#7b4fd1', '#0e8ea3', '#c0392b', '#6b7280', '#a1428f']

function readThemeVars(): ThemeVars {
  if (typeof document === 'undefined') {
    return { colors: FALLBACK_COLORS, line: '#e4e7ec', muted: '#6b7280', ink: '#15181d' }
  }
  const style = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  const colors = [1, 2, 3, 4, 5, 6, 7, 8].map((n, i) => read(`--c${n}`, FALLBACK_COLORS[i]))
  return {
    colors,
    line: read('--line', '#e4e7ec'),
    muted: read('--muted', '#6b7280'),
    ink: read('--ink', '#15181d'),
  }
}

function useThemeVars(): ThemeVars {
  const [vars, setVars] = useState<ThemeVars>(() => readThemeVars())
  useEffect(() => {
    const update = () => setVars(readThemeVars())
    update()
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [])
  return vars
}

function humanize(key: string): string {
  return key.replace(/[_-]+/g, ' ').trim()
}

function truncateLabel(value: unknown, max = 14): string {
  const s = String(value ?? '')
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

function isCountKey(key: string): boolean {
  return /count/i.test(key)
}

function isAdditiveKey(key: string): boolean {
  return /sum|count/i.test(key)
}

function isDateLike(v: string | number | null): boolean {
  return typeof v === 'string' && /^\d{4}-\d{2}(-\d{2})?/.test(v)
}

function formatMeasure(key: string, value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const num = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(num)) return String(value)
  return isCountKey(key) ? num.toLocaleString('en-IN') : inr.format(num)
}

/** Finds the single non-numeric (dimension) key and single numeric (measure) key of a Row shape. */
function pickKeys(rows: Row[]): { dimKey: string; measureKey: string } | null {
  if (!rows.length) return null
  const keys = Object.keys(rows[0])
  if (keys.length < 2) return null

  let measureKey: string | undefined
  let dimKey: string | undefined
  for (const k of keys) {
    let kind: 'number' | 'other' | null = null
    for (const r of rows) {
      const v = r[k]
      if (v === null || v === undefined) continue
      kind = typeof v === 'number' ? 'number' : 'other'
      break
    }
    if (kind === 'number' && measureKey === undefined) measureKey = k
    else if (dimKey === undefined) dimKey = k
  }
  if (!measureKey || !dimKey) return null
  return { dimKey, measureKey }
}

export function AnswerChart({ answer }: { answer: Answer }) {
  const { colors, line, muted, ink } = useThemeVars()

  const comparisonRows = answer.comparison?.rows
  if (comparisonRows && comparisonRows.length > 0) {
    return <ComparisonBarChart rows={comparisonRows} colors={colors} line={line} muted={muted} ink={ink} />
  }

  const breakdown = answer.breakdown
  if (!breakdown || breakdown.length === 0) return null
  if (breakdown.length === 1 && Object.keys(breakdown[0]).length < 2) return null

  const keys = pickKeys(breakdown)
  if (!keys) return null
  const { dimKey, measureKey } = keys

  const isChrono =
    dimKey.toLowerCase() === 'month' ||
    dimKey.toLowerCase() === 'quarter' ||
    breakdown.some((r) => isDateLike(r[dimKey] as string | number | null))

  if (isChrono) {
    const sorted = [...breakdown].sort((a, b) => String(a[dimKey] ?? '').localeCompare(String(b[dimKey] ?? '')))
    return (
      <TrendLineChart
        rows={sorted}
        dimKey={dimKey}
        measureKey={measureKey}
        colors={colors}
        line={line}
        muted={muted}
      />
    )
  }

  if (breakdown.length <= 6 && isAdditiveKey(measureKey)) {
    return (
      <DonutChart rows={breakdown} dimKey={dimKey} measureKey={measureKey} colors={colors} line={line} muted={muted} />
    )
  }

  const top10 = [...breakdown].slice(0, 10)
  return (
    <RankedBarChart rows={top10} dimKey={dimKey} measureKey={measureKey} colors={colors} line={line} muted={muted} />
  )
}

function TrendLineChart({
  rows,
  dimKey,
  measureKey,
  colors,
  line,
  muted,
}: {
  rows: Row[]
  dimKey: string
  measureKey: string
  colors: string[]
  line: string
  muted: string
}) {
  const tickStyle = useMemo(() => ({ fill: muted, fontSize: 12 }), [muted])
  return (
    <figure className="ac-chart-figure">
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={rows} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
          <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={dimKey} tickFormatter={(v) => truncateLabel(v)} stroke={muted} tick={tickStyle} />
          <YAxis
            tickFormatter={(v: number) => formatMeasure(measureKey, v)}
            stroke={muted}
            tick={tickStyle}
            width={70}
          />
          <Tooltip
            formatter={(value: number | string) => [formatMeasure(measureKey, value), humanize(measureKey)]}
            labelFormatter={(v) => String(v)}
            contentStyle={{ background: 'var(--panel)', border: `1px solid ${line}`, borderRadius: 8 }}
          />
          <Line type="monotone" dataKey={measureKey} stroke={colors[0]} strokeWidth={2} dot={{ r: 3 }} />
        </LineChart>
      </ResponsiveContainer>
      <figcaption className="ac-caption">
        {humanize(measureKey)} over {humanize(dimKey)}
      </figcaption>
    </figure>
  )
}

function DonutChart({
  rows,
  dimKey,
  measureKey,
  colors,
  line,
  muted,
}: {
  rows: Row[]
  dimKey: string
  measureKey: string
  colors: string[]
  line: string
  muted: string
}) {
  const total = rows.reduce((acc, r) => {
    const v = r[measureKey]
    return acc + (typeof v === 'number' ? v : 0)
  }, 0)
  const tickStyle = useMemo(() => ({ fill: muted, fontSize: 12 }), [muted])

  return (
    <figure className="ac-chart-figure">
      <div className="ac-donut-wrap">
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie
              data={rows}
              dataKey={measureKey}
              nameKey={dimKey}
              innerRadius={68}
              outerRadius={98}
              paddingAngle={2}
              strokeWidth={1}
              stroke="var(--panel)"
            >
              {rows.map((_, i) => (
                <Cell key={i} fill={colors[i % colors.length]} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value: number | string, name: string) => [formatMeasure(measureKey, value), name]}
              contentStyle={{ background: 'var(--panel)', border: `1px solid ${line}`, borderRadius: 8 }}
            />
            <Legend
              formatter={(value: string) => truncateLabel(value, 18)}
              wrapperStyle={{ fontSize: 12, color: tickStyle.fill }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="ac-donut-total">
          <div className="ac-donut-total-value">{formatMeasure(measureKey, total)}</div>
          <div className="ac-donut-total-label">total</div>
        </div>
      </div>
      <figcaption className="ac-caption">
        {humanize(measureKey)} by {humanize(dimKey)}
      </figcaption>
    </figure>
  )
}

function RankedBarChart({
  rows,
  dimKey,
  measureKey,
  colors,
  line,
  muted,
}: {
  rows: Row[]
  dimKey: string
  measureKey: string
  colors: string[]
  line: string
  muted: string
}) {
  const tickStyle = useMemo(() => ({ fill: muted, fontSize: 12 }), [muted])
  return (
    <figure className="ac-chart-figure">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={rows} layout="vertical" margin={{ top: 8, right: 24, left: 4, bottom: 4 }}>
          <CartesianGrid stroke={line} strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tickFormatter={(v: number) => formatMeasure(measureKey, v)} stroke={muted} tick={tickStyle} />
          <YAxis
            type="category"
            dataKey={dimKey}
            tickFormatter={(v) => truncateLabel(v)}
            stroke={muted}
            tick={tickStyle}
            width={110}
          />
          <Tooltip
            formatter={(value: number | string) => [formatMeasure(measureKey, value), humanize(measureKey)]}
            labelFormatter={(v) => String(v)}
            contentStyle={{ background: 'var(--panel)', border: `1px solid ${line}`, borderRadius: 8 }}
          />
          <Bar dataKey={measureKey} radius={[0, 4, 4, 0]}>
            {rows.map((_, i) => (
              <Cell key={i} fill={colors[i % colors.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <figcaption className="ac-caption">
        {humanize(measureKey)} by {humanize(dimKey)} (top {rows.length})
      </figcaption>
    </figure>
  )
}

function ComparisonBarChart({
  rows,
  colors,
  line,
  muted,
}: {
  rows: NonNullable<Answer['comparison']>['rows']
  colors: string[]
  line: string
  muted: string
  ink: string
}) {
  const labelKey = useMemo(() => {
    const reserved = new Set(['value', 'previous', 'delta', 'delta_pct'])
    const keys = rows.length ? Object.keys(rows[0]) : []
    return keys.find((k) => !reserved.has(k)) ?? null
  }, [rows])

  const top8 = useMemo(() => {
    return [...rows]
      .sort((a, b) => Math.abs(b.delta ?? 0) - Math.abs(a.delta ?? 0))
      .slice(0, 8)
      .map((r, i) => ({
        label: labelKey ? String(r[labelKey] ?? `#${i + 1}`) : `#${i + 1}`,
        value: r.value,
        previous: r.previous,
      }))
  }, [rows, labelKey])

  const tickStyle = useMemo(() => ({ fill: muted, fontSize: 12 }), [muted])

  return (
    <figure className="ac-chart-figure">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={top8} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
          <CartesianGrid stroke={line} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" tickFormatter={(v) => truncateLabel(v)} interval={0} stroke={muted} tick={tickStyle} />
          <YAxis tickFormatter={(v: number) => formatMeasure('value', v)} stroke={muted} tick={tickStyle} width={70} />
          <Tooltip
            formatter={(value: number | string, name: string) => [formatMeasure('value', value), name]}
            labelFormatter={(v) => String(v)}
            contentStyle={{ background: 'var(--panel)', border: `1px solid ${line}`, borderRadius: 8 }}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: muted }} />
          <Bar dataKey="value" name="Current" fill={colors[0]} radius={[4, 4, 0, 0]} />
          <Bar dataKey="previous" name="Previous" fill={colors[1]} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <figcaption className="ac-caption">Value vs previous — top {top8.length} by change</figcaption>
    </figure>
  )
}

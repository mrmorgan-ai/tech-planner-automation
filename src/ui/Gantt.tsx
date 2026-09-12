import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  addDays,
  blackoutAt,
  fromEpochDay,
  startOfWeek,
  studySegments,
  toEpochDay,
} from '../core/dates'
import { isLastWeekOfMonth } from '../core/hours'
import type { AppState, Blackout, CivilDate, Item, PhaseNumber } from '../core/types'

/**
 * A day column stretches to fill the track and only scrolls once it would get
 * narrower than a weekday letter can be read at. Floored, so the track can never
 * end up a fraction wider than its frame and raise a scrollbar for nothing.
 */
const MIN_DAY = 14
const MAX_DAY = 48
/** Must match .gantt-row in the stylesheet, or the two columns drift apart. */
const ROW = 30
/** Must match .gantt-names in the stylesheet: the frozen column's own width. */
const NAMES = 336
const PAD_DAYS = 3

type Scope = PhaseNumber | null

const LEGEND = [
  { className: 'legend-plan', label: 'the original plan' },
  { className: 'legend-pending', label: 'not started' },
  { className: 'legend-running', label: 'in progress' },
  { className: 'legend-done', label: 'done' },
  { className: 'legend-late', label: 'past its date' },
  { className: 'legend-pause', label: 'declared pause' },
  { className: 'legend-reduced', label: 'fewer hours' },
  { className: 'legend-today', label: 'today' },
]

/**
 * Effort over time, read-only: it reflects what the backlog and the board set
 * and never changes state itself. Editing a date in the backlog moves the bars
 * here, because both read the same projection.
 *
 * Day granularity, one phase at a time. The whole plan at a readable day width is
 * about three screens, while most phases fit in one with no scrolling.
 *
 * One scrolling frame with the names frozen left and the scale frozen top, the
 * spreadsheet arrangement: it keeps the horizontal scrollbar at the bottom of
 * what you are looking at rather than below two thousand pixels of rows.
 *
 * Dependencies are drawn only for the bar you point at. All 95 of them at once is
 * not a diagram: phase 3 alone would put 32 lines over 17 bars.
 */
export function Gantt({ state }: { state: AppState }) {
  const [scope, setScope] = useState<Scope>(() => activePhase(state))
  const [focused, setFocused] = useState<string | null>(null)
  const frame = useRef<HTMLDivElement>(null)
  const available = useTrackWidth(frame)

  const { items, today, roadmap } = state
  const shown = useMemo(
    () =>
      items
        .filter((item) => scope === null || item.phase === scope)
        .sort((a, b) => a.phase - b.phase || a.sortOrder - b.sortOrder),
    [items, scope],
  )

  const span = useMemo(() => timelineSpan(shown), [shown])
  const rowOf = new Map(shown.map((item, index) => [item.id, index]))

  const day = dayWidth(available, span.days)
  const x = (date: CivilDate) => (toEpochDay(date) - span.from) * day
  const width = span.days * day
  const height = shown.length * ROW

  const phase = roadmap.phases.find((entry) => entry.number === scope)
  const links = focused ? linksFor(focused, shown, rowOf) : []

  return (
    <section className="gantt">
      <h2 className="board-title">
        {phase ? `Phase ${phase.number} · ${phase.name}` : 'The whole plan'}
      </h2>

      <div className="filters">
        {roadmap.phases.map((entry) => (
          <button
            key={entry.number}
            type="button"
            className={scope === entry.number ? 'chip active' : 'chip'}
            onClick={() => setScope(entry.number)}
          >
            {entry.number}
          </button>
        ))}
        <button
          type="button"
          className={scope === null ? 'chip active' : 'chip'}
          onClick={() => setScope(null)}
        >
          All phases
          <span className="count">{items.length}</span>
        </button>
      </div>

      <ul className="legend">
        {LEGEND.map((entry) => (
          <li key={entry.label}>
            <span className={`swatch ${entry.className}`} />
            {entry.label}
          </li>
        ))}
      </ul>

      <div className="gantt-frame" ref={frame}>
        <div className="gantt-inner" style={{ width: NAMES + width }}>
          <div className="gantt-header">
            <div className="gantt-corner" />
            <Scale span={span} day={day} capacity={roadmap.weeklyHours.lastWeekOfMonth} />
          </div>

          <div className="gantt-rows">
            <div className="gantt-names" style={{ height }}>
              {shown.map((item) => (
                <div
                  key={item.id}
                  className={focused === item.id ? 'gantt-name focused' : 'gantt-name'}
                  onMouseOver={() => setFocused(item.id)}
                  onMouseOut={() => setFocused(null)}
                >
                  <span className="gantt-name-text" title={item.name}>
                    {item.name}
                  </span>
                  <RouterLink
                    className="icon-button"
                    to={`/backlog?item=${encodeURIComponent(item.id)}`}
                    title={`Open ${item.name} in the backlog`}
                    aria-label={`Open ${item.name} in the backlog`}
                  >
                    ↗
                  </RouterLink>
                </div>
              ))}
            </div>

            <div className="gantt-track" style={{ width, height }}>
              {bands(span, roadmap.blackouts).map((band) => (
                <div
                  key={`${band.kind}-${band.from}`}
                  className={`gantt-band ${band.kind}`}
                  style={{
                    left: x(band.from),
                    width: (toEpochDay(band.to) - toEpochDay(band.from) + 1) * day,
                  }}
                >
                  {band.label && <span className="gantt-band-label">{band.label}</span>}
                </div>
              ))}

              {today >= fromEpochDay(span.from) && (
                <div className="gantt-today" style={{ left: x(today) }} title={`today ${today}`} />
              )}

              {shown.map((item, index) => (
                <Bars
                  key={item.id}
                  item={item}
                  today={today}
                  top={index * ROW}
                  focused={focused === item.id}
                  day={day}
                  blackouts={roadmap.blackouts}
                  x={x}
                  onFocus={() => setFocused(item.id)}
                  onBlur={() => setFocused(null)}
                />
              ))}

              {links.length > 0 && (
                <svg className="gantt-links" width={width} height={height}>
                  {links.map((link) => (
                    <Link key={`${link.from.id}-${link.to.id}`} link={link} day={day} x={x} />
                  ))}
                </svg>
              )}
            </div>
          </div>
        </div>
      </div>

      {focused && <Missing id={focused} items={items} shown={shown} />}
    </section>
  )
}

function Scale({ span, day, capacity }: { span: Span; day: number; capacity: number }) {
  const weeks: CivilDate[] = []
  let cursor = startOfWeek(fromEpochDay(span.from))
  while (toEpochDay(cursor) < span.from + span.days) {
    weeks.push(cursor)
    cursor = addDays(cursor, 7)
  }

  return (
    <div className="gantt-scale" style={{ width: span.days * day }}>
      <div className="gantt-scale-weeks">
        {weeks.map((monday) => {
          const offset = toEpochDay(monday) - span.from
          const left = Math.max(offset, 0) * day
          // Clamped to the days that remain: a full seven-day label on the last
          // Monday overhangs the track and raises a scrollbar for nothing.
          const days = Math.min(offset + 7, span.days) - Math.max(offset, 0)
          const reduced = isLastWeekOfMonth(monday)
          return (
            <span
              key={monday}
              className={reduced ? 'gantt-week reduced' : 'gantt-week'}
              style={{ left, width: days * day }}
            >
              {label(monday)}
              {reduced && capacity > 0 && <em>{capacity}h</em>}
            </span>
          )
        })}
      </div>

      <div className="gantt-scale-days">
        {Array.from({ length: span.days }, (_, offset) => {
          const date = fromEpochDay(span.from + offset)
          return (
            <span key={date} className="gantt-day" style={{ left: offset * day, width: day }}>
              {'MTWTFSS'[(toEpochDay(date) + 3) % 7]}
            </span>
          )
        })}
      </div>
    </div>
  )
}

/**
 * One piece of bar per unbroken run of study days. A declared pause cuts the bar
 * and it resumes after: drawing straight through would claim work happens on the
 * days the plan sets aside, and those days are exactly why the end date moved.
 *
 * The reduced-hour weeks are not cut. They are still study days; only how many
 * hours fit in them changes, and the engine schedules in days.
 */
function Bars({
  item,
  today,
  top,
  focused,
  day,
  blackouts,
  x,
  onFocus,
  onBlur,
}: {
  item: Item
  today: CivilDate
  top: number
  focused: boolean
  day: number
  blackouts: readonly Blackout[]
  x: (date: CivilDate) => number
  onFocus: () => void
  onBlur: () => void
}) {
  const place = (from: CivilDate, to: CivilDate) => ({
    left: x(from),
    width: (toEpochDay(to) - toEpochDay(from) + 1) * day,
  })

  const tone = toneOf(item, today)
  const planned = studySegments(item.baselineStartDate, item.baselineEndDate, blackouts)
  const projected = studySegments(item.projectedStartDate, item.projectedEndDate, blackouts)

  return (
    <div
      className={focused ? 'gantt-row focused' : 'gantt-row'}
      style={{ top }}
      onMouseOver={onFocus}
      onMouseOut={onBlur}
    >
      {planned.map((segment) => (
        <div key={segment.from} className="gantt-ghost" style={place(segment.from, segment.to)} />
      ))}

      {projected.map((segment, index) => (
        <div
          key={segment.from}
          className={`gantt-bar ${tone}${index > 0 ? ' resumed' : ''}`}
          style={place(segment.from, segment.to)}
          title={`${item.name}: ${item.projectedStartDate} → ${item.projectedEndDate}${
            projected.length > 1 ? ' (paused in between)' : ''
          }`}
        />
      ))}
    </div>
  )
}

type DependencyLink = {
  from: { id: string; end: CivilDate; row: number }
  to: { id: string; start: CivilDate; row: number }
}

/** An elbow from the end of a predecessor down or up to the start of its successor. */
function Link({
  link,
  day,
  x,
}: {
  link: DependencyLink
  day: number
  x: (date: CivilDate) => number
}) {
  const fromX = x(link.from.end) + day
  const fromY = link.from.row * ROW + ROW / 2
  const toX = x(link.to.start)
  const toY = link.to.row * ROW + ROW / 2
  const bend = Math.max(fromX + 6, toX - 10)

  return (
    <g className="gantt-link">
      <path d={`M ${fromX} ${fromY} H ${bend} V ${toY} H ${toX}`} fill="none" />
      <circle cx={toX} cy={toY} r={2.5} />
    </g>
  )
}

/**
 * Says out loud what the diagram cannot show: a dependency that lives in another
 * phase has no row here, so its line would go nowhere.
 */
function Missing({ id, items, shown }: { id: string; items: readonly Item[]; shown: Item[] }) {
  const item = items.find((entry) => entry.id === id)
  if (!item) return null

  const visible = new Set(shown.map((entry) => entry.id))
  const outside = item.dependsOn
    .map((dependency) => items.find((entry) => entry.id === dependency))
    .filter(
      (dependency): dependency is Item => dependency !== undefined && !visible.has(dependency.id),
    )

  if (outside.length === 0) return null
  return (
    <p className="gantt-outside">
      {item.name} also waits on {outside.length} item{outside.length === 1 ? '' : 's'} outside this
      phase: {outside.map((entry) => entry.name).join(' · ')}
    </p>
  )
}

function linksFor(id: string, shown: Item[], rowOf: Map<string, number>): DependencyLink[] {
  const byId = new Map(shown.map((item) => [item.id, item]))
  const links: DependencyLink[] = []

  const push = (from: Item | undefined, to: Item | undefined) => {
    if (!from || !to) return
    const fromRow = rowOf.get(from.id)
    const toRow = rowOf.get(to.id)
    if (fromRow === undefined || toRow === undefined) return
    links.push({
      from: { id: from.id, end: from.projectedEndDate, row: fromRow },
      to: { id: to.id, start: to.projectedStartDate, row: toRow },
    })
  }

  const item = byId.get(id)
  if (!item) return links

  // Both directions: what it waits on, and what waits on it.
  for (const dependency of item.dependsOn) push(byId.get(dependency), item)
  for (const other of shown) {
    if (other.dependsOn.includes(id)) push(item, other)
  }
  return links
}

type Band = { kind: 'pause' | 'reduced'; from: CivilDate; to: CivilDate; label?: string }

/**
 * The background of the track: declared pauses carry their reason, and the last
 * week of each month is tinted because fewer hours are available in it.
 */
function bands(span: Span, blackouts: readonly Blackout[]): Band[] {
  const found: Band[] = []
  const first = fromEpochDay(span.from)
  const last = fromEpochDay(span.from + span.days - 1)

  for (const blackout of blackouts) {
    if (blackout.to < first || blackout.from > last) continue
    found.push({
      kind: 'pause',
      from: blackout.from < first ? first : blackout.from,
      to: blackout.to > last ? last : blackout.to,
      label: blackout.reason,
    })
  }

  // Clipped to the span like the pauses above: an unclipped seven-day band whose
  // Monday is the last day of the track sticks out and raises a scrollbar with
  // nothing behind it.
  let monday = startOfWeek(first)
  while (monday <= last) {
    if (isLastWeekOfMonth(monday) && !blackoutAt(monday, blackouts)) {
      const to = addDays(monday, 6)
      found.push({
        kind: 'reduced',
        from: monday < first ? first : monday,
        to: to > last ? last : to,
      })
    }
    monday = addDays(monday, 7)
  }
  return found
}

/**
 * The frame's inner width, measured on layout and kept in step with the window.
 *
 * Deliberately not a ResizeObserver: its callbacks are tied to the rendering
 * lifecycle, so in a tab that is not painting they never arrive and the chart
 * silently falls back to its minimum day width. In this layout the frame only
 * changes width when the window does.
 */
function useTrackWidth(ref: React.RefObject<HTMLDivElement | null>): number {
  const [width, setWidth] = useState(0)

  const measure = useCallback(() => {
    const element = ref.current
    if (element) setWidth(element.clientWidth - NAMES)
  }, [ref])

  useLayoutEffect(() => {
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [measure])

  return width
}

/**
 * Fill the track when the days fit, scroll when they do not. Floored rather than
 * rounded: a track a fraction wider than its frame raises a scrollbar that has
 * nothing to scroll.
 */
function dayWidth(available: number, days: number): number {
  if (available <= 0 || days === 0) return MIN_DAY
  return Math.min(MAX_DAY, Math.max(MIN_DAY, Math.floor(available / days)))
}

type Span = { from: number; days: number }

/** The shown items plus a few days of margin, so the first bar is not flush. */
function timelineSpan(items: readonly Item[]): Span {
  if (items.length === 0) return { from: toEpochDay('2026-01-01'), days: 30 }
  const starts = items.flatMap((item) => [item.baselineStartDate, item.projectedStartDate])
  const ends = items.flatMap((item) => [item.baselineEndDate, item.projectedEndDate])
  const from = toEpochDay(starts.reduce(min)) - PAD_DAYS
  const to = toEpochDay(ends.reduce(max)) + PAD_DAYS
  return { from, days: to - from + 1 }
}

function toneOf(item: Item, today: CivilDate): string {
  if (item.state === 'done') return 'done'
  if (item.projectedEndDate < today) return 'late'
  return item.state === 'in_progress' ? 'running' : 'pending'
}

function activePhase(state: AppState): Scope {
  const open = state.roadmap.phases.find((phase) =>
    state.items.some((item) => item.phase === phase.number && item.state !== 'done'),
  )
  return open?.number ?? state.roadmap.phases[0]?.number ?? null
}

/** Always the month and the day: "Dec 14" reads on its own, "14" does not. */
function label(monday: CivilDate): string {
  const date = new Date(`${monday}T12:00:00Z`)
  const month = date.toLocaleDateString('en', { month: 'short', timeZone: 'UTC' })
  return `${month} ${date.getUTCDate()}`
}

function min(a: CivilDate, b: CivilDate): CivilDate {
  return a < b ? a : b
}

function max(a: CivilDate, b: CivilDate): CivilDate {
  return a > b ? a : b
}

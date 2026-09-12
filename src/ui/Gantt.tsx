import { useState } from 'react'
import { toEpochDay } from '../core/dates'
import type { AppState, CivilDate, Item, Phase, PhaseNumber } from '../core/types'

/**
 * Effort over time, read-only: it reflects what the backlog and the board set
 * and never changes state itself.
 *
 * Two bars per row — a faint ghost for the original plan and a solid one for
 * the current projection. A solid bar sitting to the right of its ghost is the
 * shape of a slip. Grouped by phase, because 65 bars at once is noise.
 */
export function Gantt({ state }: { state: AppState }) {
  const [open, setOpen] = useState<Set<PhaseNumber>>(new Set())
  const { items, today, roadmap } = state

  const span = timelineSpan(items)
  const at = (date: CivilDate) => ((toEpochDay(date) - span.from) / span.days) * 100

  function toggle(phase: PhaseNumber) {
    const next = new Set(open)
    if (!next.delete(phase)) next.add(phase)
    setOpen(next)
  }

  return (
    <section className="gantt">
      <p className="muted gantt-legend">
        Faint bar: the original plan. Solid bar: where it stands now. Shaded bands are the
        non-study periods, so a gap reads as a planned pause and not as a slip.
      </p>

      <div className="gantt-grid">
        <div className="gantt-labels">
          <div className="gantt-head" />
          {roadmap.phases.map((phase) => (
            <PhaseLabel
              key={phase.number}
              phase={phase}
              open={open.has(phase.number)}
              items={itemsOf(items, phase)}
              onToggle={() => toggle(phase.number)}
            />
          ))}
        </div>

        <div className="gantt-track">
          <div className="gantt-head">
            {yearMarks(span).map((mark) => (
              <span key={mark.date} className="gantt-mark" style={{ left: `${at(mark.date)}%` }}>
                {mark.label}
              </span>
            ))}
          </div>

          <div className="gantt-body">
            {roadmap.blackouts.map((blackout) => (
              <div
                key={blackout.from}
                className="gantt-blackout"
                title={blackout.reason}
                style={{ left: `${at(blackout.from)}%`, width: `${at(blackout.to) - at(blackout.from)}%` }}
              />
            ))}

            <div className="gantt-today" style={{ left: `${at(today)}%` }} title={`today ${today}`} />

            {roadmap.phases.map((phase) => {
              const inPhase = itemsOf(items, phase)
              return (
                <div key={phase.number} className="gantt-group">
                  <Bars
                    baseline={rangeOf(inPhase, 'baseline')}
                    projected={rangeOf(inPhase, 'projected')}
                    tone="phase"
                    at={at}
                  />
                  {open.has(phase.number) &&
                    inPhase.map((item) => (
                      <Bars
                        key={item.id}
                        baseline={[item.baselineStartDate, item.baselineEndDate]}
                        projected={[item.projectedStartDate, item.projectedEndDate]}
                        tone={toneOf(item, today)}
                        label={item.name}
                        at={at}
                      />
                    ))}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}

function PhaseLabel({
  phase,
  items,
  open,
  onToggle,
}: {
  phase: Phase
  items: Item[]
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="gantt-group">
      <button type="button" className="gantt-phase" aria-expanded={open} onClick={onToggle}>
        <span className="disclosure">{open ? '▾' : '▸'}</span>
        <span className="phase-index">{phase.number}</span>
        <span className="phase-name">{phase.name}</span>
      </button>
      {open &&
        items.map((item) => (
          <div key={item.id} className="gantt-item-label" title={item.name}>
            {item.name}
          </div>
        ))}
    </div>
  )
}

function Bars({
  baseline,
  projected,
  tone,
  label,
  at,
}: {
  baseline: [CivilDate, CivilDate] | null
  projected: [CivilDate, CivilDate] | null
  tone: string
  label?: string
  at: (date: CivilDate) => number
}) {
  if (!baseline || !projected) return <div className="gantt-row" />
  const place = ([from, to]: [CivilDate, CivilDate]) => ({
    left: `${at(from)}%`,
    // One day of width for a single-day item, which would otherwise be invisible.
    width: `${Math.max(at(to) - at(from), 0.4)}%`,
  })

  return (
    <div className="gantt-row">
      <div className="gantt-ghost" style={place(baseline)} />
      <div
        className={`gantt-bar ${tone}`}
        style={place(projected)}
        title={label ? `${label}: ${projected[0]} → ${projected[1]}` : `${projected[0]} → ${projected[1]}`}
      />
    </div>
  )
}

function itemsOf(items: readonly Item[], phase: Phase): Item[] {
  return items
    .filter((item) => item.phase === phase.number)
    .sort((a, b) => a.sortOrder - b.sortOrder)
}

function rangeOf(items: Item[], which: 'baseline' | 'projected'): [CivilDate, CivilDate] | null {
  if (items.length === 0) return null
  const starts = items.map((item) =>
    which === 'baseline' ? item.baselineStartDate : item.projectedStartDate,
  )
  const ends = items.map((item) =>
    which === 'baseline' ? item.baselineEndDate : item.projectedEndDate,
  )
  return [starts.reduce(min), ends.reduce(max)]
}

function toneOf(item: Item, today: CivilDate): string {
  if (item.state === 'done') return 'done'
  if (item.projectedEndDate < today) return 'late'
  return item.state === 'in_progress' ? 'running' : 'pending'
}

/** The whole plan plus a small margin, so the first and last bar are not flush. */
function timelineSpan(items: readonly Item[]): { from: number; days: number } {
  if (items.length === 0) return { from: 0, days: 1 }
  const starts = items.flatMap((item) => [item.baselineStartDate, item.projectedStartDate])
  const ends = items.flatMap((item) => [item.baselineEndDate, item.projectedEndDate])
  const from = toEpochDay(starts.reduce(min)) - 7
  const to = toEpochDay(ends.reduce(max)) + 7
  return { from, days: to - from }
}

function yearMarks(span: { from: number; days: number }): { date: CivilDate; label: string }[] {
  const marks: { date: CivilDate; label: string }[] = []
  const start = new Date(span.from * 86400000)
  const cursor = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), 1))
  while (cursor.getTime() / 86400000 < span.from + span.days) {
    const date = cursor.toISOString().slice(0, 10)
    if (cursor.getTime() / 86400000 >= span.from) {
      const month = cursor.toLocaleDateString('en', { month: 'short', timeZone: 'UTC' })
      // The year only where it resolves an ambiguity: the plan crosses into a
      // new year, and a bare "Jan" does not say which one.
      const firstOfYear = marks.length === 0 || cursor.getUTCMonth() === 0
      marks.push({ date, label: firstOfYear ? `${month} ${cursor.getUTCFullYear()}` : month })
    }
    cursor.setUTCMonth(cursor.getUTCMonth() + 1)
  }
  return marks
}

function min(a: CivilDate, b: CivilDate): CivilDate {
  return a < b ? a : b
}

function max(a: CivilDate, b: CivilDate): CivilDate {
  return a > b ? a : b
}

import { useState } from 'react'
import { STATES } from '../core/constants'
import {
  hasSlipped,
  isOverdue,
  matchesFilter,
  slipDays,
  ITEM_FILTERS,
  type ItemFilter,
} from '../core/selectors'
import type { AppState, Item, State } from '../core/types'
import { PhaseSidebar, type PhaseSelection } from './PhaseSidebar'
import type { Store } from './useAppState'

const STATE_LABEL: Record<State, string> = {
  pending: 'Pending',
  in_progress: 'In progress',
  done: 'Done',
}

const FILTER_LABEL: Record<ItemFilter, string> = {
  all: 'All',
  pending: 'Pending',
  in_progress: 'In progress',
  overdue: 'Overdue',
  done: 'Done',
}

/**
 * The detail view, and the surface the rest hangs off: the Gantt only reflects
 * what is set here or on the board. One phase at a time, because 65 rows in a
 * single scroll is a list you stop reading.
 *
 * Topics stay visible under each name; the long note and the dependency list
 * live in the row you expand. Dependencies are shown as information, never as a
 * lock — nothing here stops you starting anything.
 */
export function Backlog({ state, pendingId, changeState }: Store & { state: AppState }) {
  const [filter, setFilter] = useState<ItemFilter>('all')
  const [phase, setPhase] = useState<PhaseSelection>(state.roadmap.phases[0]?.number ?? null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const inPhase = state.items.filter((item) => phase === null || item.phase === phase)
  const visible = inPhase
    .filter((item) => matchesFilter(item, filter, state.today))
    .sort((a, b) => a.phase - b.phase || a.sortOrder - b.sortOrder)

  const names = new Map(state.items.map((item) => [item.id, item.name]))

  return (
    <section className="backlog">
      <PhaseSidebar
        phases={state.roadmap.phases}
        items={state.items}
        selected={phase}
        onSelect={setPhase}
      />

      <div className="items-pane">
        <div className="filters">
          {ITEM_FILTERS.map((candidate) => (
            <button
              key={candidate}
              type="button"
              className={candidate === filter ? 'chip active' : 'chip'}
              onClick={() => setFilter(candidate)}
            >
              {FILTER_LABEL[candidate]}
              <span className="count">
                {inPhase.filter((item) => matchesFilter(item, candidate, state.today)).length}
              </span>
            </button>
          ))}
        </div>

        {visible.length === 0 ? (
          <p className="empty">Nothing matches this filter in this phase.</p>
        ) : (
          <table className="items">
            <thead>
              <tr>
                <th className="col-state">State</th>
                <th className="col-type">Type</th>
                <th className="col-name">Item</th>
                <th className="col-date">Start</th>
                <th className="col-date">End</th>
                <th className="col-price">Price</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((item) => (
                <Row
                  key={item.id}
                  item={item}
                  today={state.today}
                  busy={pendingId === item.id}
                  open={expanded === item.id}
                  names={names}
                  showPhase={phase === null}
                  onToggle={() => setExpanded(expanded === item.id ? null : item.id)}
                  onChange={(next) => void changeState(item.id, next)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

function Row({
  item,
  today,
  busy,
  open,
  names,
  showPhase,
  onToggle,
  onChange,
}: {
  item: Item
  today: string
  busy: boolean
  open: boolean
  names: Map<string, string>
  showPhase: boolean
  onToggle: () => void
  onChange: (next: State) => void
}) {
  const late = isOverdue(item, today)
  const slipped = hasSlipped(item)
  const rowClass = [late ? 'overdue' : '', item.state === 'done' ? 'done' : '', open ? 'open' : '']
    .filter(Boolean)
    .join(' ')

  return (
    <>
      <tr className={rowClass || undefined}>
        <td className="col-state">
          <select
            value={item.state}
            disabled={busy}
            aria-label={`State of ${item.name}`}
            onChange={(event) => onChange(event.target.value as State)}
          >
            {STATES.map((candidate) => (
              <option key={candidate} value={candidate}>
                {STATE_LABEL[candidate]}
              </option>
            ))}
          </select>
        </td>

        <td className="col-type">
          <span className="type-tag">{item.type}</span>
        </td>

        <td className="col-name">
          <div className="name-line">
            <button
              type="button"
              className="disclosure"
              aria-expanded={open}
              aria-label={`Notes and dependencies of ${item.name}`}
              onClick={onToggle}
            >
              {open ? '▾' : '▸'}
            </button>
            {item.link ? (
              <a href={item.link} target="_blank" rel="noreferrer">
                {item.name}
              </a>
            ) : (
              <span className="name">{item.name}</span>
            )}
            {showPhase && <span className="phase-tag">phase {item.phase}</span>}
          </div>
          {item.skills.length > 0 && (
            <div className="skills">
              {item.skills.map((skill) => (
                <span key={skill} className="skill">
                  {skill}
                </span>
              ))}
            </div>
          )}
        </td>

        <td className="col-date">
          <div>{item.projectedStartDate}</div>
          {slipped && <div className="planned">was {item.baselineStartDate}</div>}
        </td>

        <td className={late ? 'col-date late' : 'col-date'}>
          <div>{item.projectedEndDate}</div>
          {slipped && (
            <div className="planned">
              was {item.baselineEndDate} ({signed(slipDays(item))}d)
            </div>
          )}
        </td>

        <td className="col-price">{item.price}</td>
      </tr>

      {open && (
        <tr className="detail">
          <td colSpan={2} />
          <td colSpan={4}>
            {item.notes && (
              <div className="detail-line">
                <span className="detail-label">What exactly</span>
                <span className="notes">{item.notes}</span>
              </div>
            )}

            <div className="detail-line">
              <span className="detail-label">Depends on</span>
              <span className="depends">
                {item.dependsOn.length === 0
                  ? 'nothing — it can be started at any time'
                  : item.dependsOn.map((id) => names.get(id) ?? id).join(' · ')}
              </span>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function signed(days: number): string {
  return days > 0 ? `+${days}` : String(days)
}

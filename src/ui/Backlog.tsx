import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { STATES } from '../core/constants'
import {
  hasSlipped,
  isOverdue,
  matchesFilter,
  slipDays,
  ITEM_FILTERS,
  type ItemFilter,
} from '../core/selectors'
import type { AppState, CivilDate, Item, State } from '../core/types'
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
 * Dates are editable here. What you edit is the baseline — the plan — and the
 * server recomputes every projection from it, so anything that depends on the
 * item you moved follows. Dependencies are shown as information, never as a
 * lock: nothing here stops you starting anything.
 */
export function Backlog({
  state,
  pendingId,
  changeState,
  changeDates,
}: Store & { state: AppState }) {
  const [filter, setFilter] = useState<ItemFilter>('all')
  const [phase, setPhase] = useState<PhaseSelection>(state.roadmap.phases[0]?.number ?? null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [params, setParams] = useSearchParams()

  /**
   * `?item=` is how the Gantt hands a row over. Opening it means switching to its
   * phase, clearing the filter that might hide it, and expanding it — then
   * dropping the parameter, so a later reload does not reopen it.
   */
  const requested = params.get('item')
  useEffect(() => {
    if (!requested) return
    const target = state.items.find((item) => item.id === requested)
    if (target) {
      setPhase(target.phase)
      setFilter('all')
      setExpanded(target.id)
    }
    setParams({}, { replace: true })
  }, [requested, state.items, setParams])

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
                <th className="col-edit" />
                <th className="col-resources">Resources</th>
                <th className="col-price">Price</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((item) => (
                <Row
                  key={item.id}
                  item={item}
                  today={state.today}
                  floor={state.roadmap.startDate}
                  busy={pendingId === item.id}
                  open={expanded === item.id}
                  editing={editing === item.id}
                  names={names}
                  showPhase={phase === null}
                  onToggle={() => setExpanded(expanded === item.id ? null : item.id)}
                  onEdit={() => setEditing(editing === item.id ? null : item.id)}
                  onChange={(next) => void changeState(item.id, next)}
                  onSaveDates={async (start, end) => {
                    if (await changeDates(item.id, start, end)) setEditing(null)
                  }}
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
  floor,
  busy,
  open,
  editing,
  names,
  showPhase,
  onToggle,
  onEdit,
  onChange,
  onSaveDates,
}: {
  item: Item
  today: string
  floor: CivilDate | ''
  busy: boolean
  open: boolean
  editing: boolean
  names: Map<string, string>
  showPhase: boolean
  onToggle: () => void
  onEdit: () => void
  onChange: (next: State) => void
  onSaveDates: (start: CivilDate, end: CivilDate) => void
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
              aria-label={`Details of ${item.name}`}
              onClick={onToggle}
            >
              {open ? '▾' : '▸'}
            </button>
            <span className="name">{item.name}</span>
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

        {editing ? (
          <DateEditor item={item} floor={floor} busy={busy} onSave={onSaveDates} onCancel={onEdit} />
        ) : (
          <>
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

            <td className="col-edit">
              <button
                type="button"
                className="icon-button"
                disabled={busy}
                aria-label={`Edit the dates of ${item.name}`}
                title="Edit the planned dates"
                onClick={onEdit}
              >
                ✎
              </button>
            </td>
          </>
        )}

        <td className="col-resources">
          <div className="resources">
            {item.link && (
              <a href={item.link} target="_blank" rel="noreferrer">
                {hostOf(item.link)}
              </a>
            )}
            {item.resources.map((resource) => (
              <a key={resource.url} href={resource.url} target="_blank" rel="noreferrer">
                {resource.label}
              </a>
            ))}
            {!item.link && item.resources.length === 0 && <span className="faint">—</span>}
          </div>
        </td>

        <td className="col-price">{item.price}</td>
      </tr>

      {open && (
        <tr className="detail">
          <td colSpan={2} />
          <td colSpan={6}>
            {item.duration && (
              <div className="detail-line">
                <span className="detail-label">Duration</span>
                <span>{item.duration}</span>
              </div>
            )}

            {item.notes && (
              <div className="detail-line">
                <span className="detail-label">What it is</span>
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

/**
 * Editing writes the baseline, so the inputs start from the baseline and not
 * from the projection — otherwise a slip would be silently promoted into the
 * plan the moment you saved.
 */
function DateEditor({
  item,
  floor,
  busy,
  onSave,
  onCancel,
}: {
  item: Item
  floor: CivilDate | ''
  busy: boolean
  onSave: (start: CivilDate, end: CivilDate) => void
  onCancel: () => void
}) {
  const [start, setStart] = useState(item.baselineStartDate)
  const [end, setEnd] = useState(item.baselineEndDate)
  const invalid = end < start

  return (
    <>
      <td className="col-date">
        <input
          type="date"
          value={start}
          min={floor || undefined}
          disabled={busy}
          aria-label={`Planned start of ${item.name}`}
          onChange={(event) => setStart(event.target.value)}
        />
      </td>

      <td className="col-date">
        <input
          type="date"
          value={end}
          min={start}
          disabled={busy}
          aria-label={`Planned end of ${item.name}`}
          onChange={(event) => setEnd(event.target.value)}
        />
        {invalid && <div className="planned bad">end is before start</div>}
      </td>

      <td className="col-edit">
        <div className="edit-actions">
          <button
            type="button"
            className="icon-button save"
            disabled={busy || invalid}
            aria-label="Save the dates"
            title="Save"
            onClick={() => onSave(start, end)}
          >
            ✓
          </button>
          <button
            type="button"
            className="icon-button"
            disabled={busy}
            aria-label="Cancel editing"
            title="Cancel"
            onClick={onCancel}
          >
            ✕
          </button>
        </div>
      </td>
    </>
  )
}

/** The domain, so a link says where it goes instead of saying "open". */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return 'link'
  }
}

function signed(days: number): string {
  return days > 0 ? `+${days}` : String(days)
}

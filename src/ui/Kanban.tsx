import { useState, type DragEvent } from 'react'
import {
  estimatedHours,
  hoursInWeek,
  inWeek,
  isLastWeekOfMonth,
  sumHours,
  weekOf,
} from '../core/hours'
import { BOARD_COLUMNS, groupByState, isOverdue, unfinishedDependencies } from '../core/selectors'
import type { Week } from '../core/hours'
import type { AppState, Item, Phase, State } from '../core/types'
import type { Store } from './useAppState'

const COLUMN_LABEL: Record<State, string> = {
  pending: 'Pending',
  in_progress: 'In progress',
  done: 'Done',
}

/**
 * The day-to-day surface, over the same `state` field as the backlog — never a
 * second source of truth.
 *
 * Scoped to the active phase and nothing else: no phase picker, because the
 * board is for the work in hand and the backlog is where you go to look around.
 * Inside Pending, what this week touches is separated from what comes later —
 * a week holds one to five items in this roadmap, too few to be a column of its
 * own, but the scope you actually plan against.
 *
 * The board still never blocks. An item started before its dependencies are
 * done is marked, not refused.
 */
export function Kanban({ state, pendingId, changeState }: Store & { state: AppState }) {
  const [dragging, setDragging] = useState<Item | null>(null)
  const [over, setOver] = useState<State | null>(null)

  const phase = activePhase(state)
  const items = state.items.filter((item) => phase === null || item.phase === phase.number)
  const columns = groupByState(items)

  const capacity = state.roadmap.weeklyHours
  // Before the plan starts, the current week ends before any of it: showing that
  // week is correct and useless. The scope is then the week the plan begins.
  const anchor =
    state.roadmap.startDate !== '' && state.today < state.roadmap.startDate
      ? state.roadmap.startDate
      : state.today
  const week = weekOf(anchor, capacity)
  const started = anchor === state.today
  const thisWeek = new Set(inWeek(items, week).map((item) => item.id))

  /**
   * The dropped id comes from the drag payload, not from React state: the
   * browser carries it for exactly this, and reading it here means the drop
   * never depends on a re-render having landed between dragstart and drop.
   */
  function drop(event: DragEvent<HTMLDivElement>, column: State) {
    event.preventDefault()
    setDragging(null)
    setOver(null)
    const id = event.dataTransfer.getData('text/plain')
    const item = state.items.find((candidate) => candidate.id === id)
    if (item && item.state !== column) void changeState(item.id, column)
  }

  return (
    <section className="kanban">
      <h2 className="board-title">
        {phase ? `Phase ${phase.number} · ${phase.name}` : 'Everything'}
      </h2>

      <WeekPanel
        week={week}
        started={started}
        scheduled={hoursInWeek(items, week, state.roadmap.blackouts)}
      />

      <div className="board">
        {BOARD_COLUMNS.map((column) => (
          <div
            key={column}
            className={over === column && dragging?.state !== column ? 'column over' : 'column'}
            onDragOver={(event) => {
              // Preventing the dragover default is what marks an element as a
              // valid drop target; without it the browser refuses the drop.
              event.preventDefault()
              setOver(column)
            }}
            onDragLeave={() => setOver((current) => (current === column ? null : current))}
            onDrop={(event) => drop(event, column)}
          >
            <header className="column-head">
              <span className="column-name">{COLUMN_LABEL[column]}</span>
              <Totals items={columns[column].length} hours={sumHours(columns[column])} />
            </header>

            {columns[column].length === 0 ? (
              <p className="column-empty">Nothing here.</p>
            ) : column === 'pending' ? (
              <Split
                items={columns[column]}
                thisWeek={thisWeek}
                week={week}
                state={state}
                pendingId={pendingId}
                onDragStart={setDragging}
                onDragEnd={() => {
                  setDragging(null)
                  setOver(null)
                }}
              />
            ) : (
              columns[column].map((item) => (
                <Card
                  key={item.id}
                  item={item}
                  today={state.today}
                  blockers={unfinishedDependencies(item, state.items)}
                  busy={pendingId === item.id}
                  onDragStart={() => setDragging(item)}
                  onDragEnd={() => {
                    setDragging(null)
                    setOver(null)
                  }}
                />
              ))
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

/**
 * Pending, cut in two: this week above the line, the rest of the phase below.
 * Both groups keep their heading even when empty — an empty "this week" is
 * information, not a reason to hide the label.
 */
function Split({
  items,
  thisWeek,
  week,
  state,
  pendingId,
  onDragStart,
  onDragEnd,
}: {
  items: Item[]
  thisWeek: Set<string>
  week: Week
  state: AppState
  pendingId: string | null
  onDragStart: (item: Item) => void
  onDragEnd: () => void
}) {
  const now = items.filter((item) => thisWeek.has(item.id))
  const later = items.filter((item) => !thisWeek.has(item.id))

  return (
    <>
      {[
        {
          label: 'This week',
          group: now,
          empty: 'nothing scheduled this week',
          // The share of each item that actually lands in the week, so this
          // total and the one in the header are the same number.
          hours: hoursInWeek(now, week, state.roadmap.blackouts),
        },
        {
          label: 'Later in this phase',
          group: later,
          empty: 'nothing left after this week',
          hours: sumHours(later),
        },
      ].map(({ label, group, empty, hours }) => (
        <div key={label} className="group">
          <div className="group-head">
            <span className="group-name">{label}</span>
            <Totals items={group.length} hours={hours} />
          </div>
          {group.length === 0 ? (
            <p className="column-empty">{empty}</p>
          ) : (
            group.map((item) => (
              <Card
                key={item.id}
                item={item}
                today={state.today}
                blockers={unfinishedDependencies(item, state.items)}
                busy={pendingId === item.id}
                onDragStart={() => onDragStart(item)}
                onDragEnd={onDragEnd}
              />
            ))
          )}
        </div>
      ))}
    </>
  )
}

/**
 * The week as its own panel rather than a line of subtitle: label above value,
 * and the one comparison that matters — scheduled against available — drawn as a
 * meter, because "7.6 of 15" is a ratio and a ratio is read faster as a bar.
 */
function WeekPanel({
  week,
  started,
  scheduled,
}: {
  week: Week
  started: boolean
  scheduled: number
}) {
  const declared = week.hours > 0
  const ratio = declared ? Math.min(scheduled / week.hours, 1) : 0
  const over = declared && scheduled > week.hours

  return (
    <div className="week-panel">
      <div className="stat">
        <div className="stat-label">Week</div>
        <div className="stat-value">{range(week)}</div>
        <div className="stat-note">{started ? 'in progress' : 'the plan starts here'}</div>
      </div>

      <div className="stat">
        <div className="stat-label">Available</div>
        <div className="stat-value">{declared ? `${week.hours}h` : '—'}</div>
        <div className="stat-note">
          {declared
            ? isLastWeekOfMonth(week.from)
              ? 'last week of the month'
              : 'normal week'
            : 'no capacity declared'}
        </div>
      </div>

      <div className="stat">
        <div className="stat-label">Scheduled</div>
        <div className={over ? 'stat-value bad' : 'stat-value'}>{scheduled.toFixed(1)}h</div>
        <div className="stat-note">
          {declared ? (
            <>
              <div className="meter">
                <div
                  className={over ? 'meter-fill over' : 'meter-fill'}
                  style={{ width: `${Math.round(ratio * 100)}%` }}
                />
              </div>
              {Math.round((scheduled / week.hours) * 100)}% of the week
            </>
          ) : (
            'nothing to compare against'
          )}
        </div>
      </div>
    </div>
  )
}

/** Two labelled numbers, inline: the recommended shape for secondary figures. */
function Totals({ items, hours }: { items: number; hours: number }) {
  return (
    <span className="totals">
      <span className="total">
        <span className="total-label">Items</span> {items}
      </span>
      <span className="total">
        <span className="total-label">Hours</span> {hours.toFixed(1)}h
      </span>
    </span>
  )
}

/** "Sep 14 – 20", or both months when the week straddles one. */
function range(week: Week): string {
  const month = (date: string) =>
    new Date(`${date}T12:00:00Z`).toLocaleDateString('en', { month: 'short', timeZone: 'UTC' })
  const day = (date: string) => String(Number(date.slice(8, 10)))
  const sameMonth = week.from.slice(0, 7) === week.to.slice(0, 7)
  return sameMonth
    ? `${month(week.from)} ${day(week.from)} – ${day(week.to)}`
    : `${month(week.from)} ${day(week.from)} – ${month(week.to)} ${day(week.to)}`
}

function Card({
  item,
  today,
  blockers,
  busy,
  onDragStart,
  onDragEnd,
}: {
  item: Item
  today: string
  blockers: Item[]
  busy: boolean
  onDragStart: () => void
  onDragEnd: () => void
}) {
  const late = isOverdue(item, today)
  const hours = estimatedHours(item)
  // Started or finished with dependencies still open. Reported, never refused.
  const outOfOrder = item.state !== 'pending' && blockers.length > 0

  return (
    <article
      className={[ 'card', busy ? 'busy' : '', outOfOrder ? 'out-of-order' : '' ]
        .filter(Boolean)
        .join(' ')}
      draggable={!busy}
      onDragStart={(event) => {
        // Firefox only starts a drag when the event carries data.
        event.dataTransfer.setData('text/plain', item.id)
        event.dataTransfer.effectAllowed = 'move'
        onDragStart()
      }}
      onDragEnd={onDragEnd}
    >
      <div className="card-head">
        <span className="type-tag">{item.type}</span>
        <span className="card-hours">{hours === null ? 'no estimate' : `${trim(hours)}h`}</span>
        <span className={late ? 'card-date bad' : 'card-date'}>
          {item.state === 'done' ? 'ended' : 'ends'} {item.projectedEndDate}
        </span>
      </div>

      <div className="card-name">{item.name}</div>

      {blockers.length > 0 && (
        <div
          className={outOfOrder ? 'card-note warn' : 'card-note'}
          title={blockers.map((blocker) => blocker.name).join('\n')}
        >
          {outOfOrder ? 'started out of order — waiting on ' : 'depends on: '}
          {summarize(blockers)}
        </div>
      )}
    </article>
  )
}

/**
 * Two names and a count, never the whole list: a phase-closing milestone depends
 * on everything before it, and printing all eight turns the card into the note.
 */
function summarize(blockers: Item[]): string {
  const shown = blockers.slice(0, 2).map((blocker) => blocker.name)
  const rest = blockers.length - shown.length
  return rest === 0 ? shown.join(' · ') : `${shown.join(' · ')} +${rest} more`
}

/**
 * The phase the board opens on: the first with work left. A finished phase is
 * never where the day-to-day happens.
 */
function activePhase(state: AppState): Phase | null {
  const open = state.roadmap.phases.find((phase) =>
    state.items.some((item) => item.phase === phase.number && item.state !== 'done'),
  )
  return open ?? state.roadmap.phases[state.roadmap.phases.length - 1] ?? null
}

function trim(hours: number): string {
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(1)
}

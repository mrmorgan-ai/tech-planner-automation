import { useState, type DragEvent } from 'react'
import {
  BOARD_COLUMNS,
  groupByState,
  isOverdue,
  unfinishedDependencies,
} from '../core/selectors'
import type { AppState, Item, Phase, State } from '../core/types'
import { PhaseSidebar, type PhaseSelection } from './PhaseSidebar'
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
 * Governing rule from the spec: the board never blocks anything. No WIP limit
 * (the count is information), and an unfinished dependency is a note on the
 * card, not a fence. Every pair of columns is a legal move, in both directions.
 */
export function Kanban({ state, pendingId, changeState }: Store & { state: AppState }) {
  const [phase, setPhase] = useState<PhaseSelection>(() => openingPhase(state))
  const [dragging, setDragging] = useState<Item | null>(null)
  const [over, setOver] = useState<State | null>(null)

  const items = state.items.filter((item) => phase === null || item.phase === phase)
  const columns = groupByState(items)

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
    <section className="backlog">
      <PhaseSidebar
        phases={state.roadmap.phases}
        items={state.items}
        selected={phase}
        onSelect={setPhase}
      />

      <div className="board">
        {BOARD_COLUMNS.map((column) => (
          <div
            key={column}
            className={over === column && dragging?.state !== column ? 'column over' : 'column'}
            onDragOver={(event) => {
              // Without this the browser refuses the drop: preventing the
              // dragover default is what marks an element as a valid target.
              event.preventDefault()
              setOver(column)
            }}
            onDragLeave={() => setOver((current) => (current === column ? null : current))}
            onDrop={(event) => drop(event, column)}
          >
            <header className="column-head">
              <span>{COLUMN_LABEL[column]}</span>
              <span className="count">{columns[column].length}</span>
            </header>

            {columns[column].length === 0 ? (
              <p className="column-empty">Nothing here.</p>
            ) : (
              columns[column].map((item) => (
                <Card
                  key={item.id}
                  item={item}
                  today={state.today}
                  blockers={unfinishedDependencies(item, state.items)}
                  busy={pendingId === item.id}
                  showPhase={phase === null}
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

function Card({
  item,
  today,
  blockers,
  busy,
  showPhase,
  onDragStart,
  onDragEnd,
}: {
  item: Item
  today: string
  blockers: Item[]
  busy: boolean
  showPhase: boolean
  onDragStart: () => void
  onDragEnd: () => void
}) {
  const late = isOverdue(item, today)

  return (
    <article
      className={busy ? 'card busy' : 'card'}
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
        {showPhase && <span className="phase-tag">phase {item.phase}</span>}
        <span className={late ? 'card-date bad' : 'card-date'}>
          {item.state === 'done' ? 'ended' : 'ends'} {item.projectedEndDate}
        </span>
      </div>

      <div className="card-name">{item.name}</div>

      {blockers.length > 0 && (
        <div className="card-note" title={blockers.map((blocker) => blocker.name).join('\n')}>
          depends on: {summarize(blockers)}
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
 * The board opens on the first phase that still has work, not always on phase 1:
 * this is the day-to-day view, and a finished phase is never where you look.
 */
function openingPhase(state: AppState): PhaseSelection {
  const phases = state.roadmap.phases
  const open = phases.find((phase: Phase) =>
    state.items.some((item) => item.phase === phase.number && item.state !== 'done'),
  )
  return open?.number ?? phases[0]?.number ?? null
}

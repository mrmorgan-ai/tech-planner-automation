import { phaseProgress } from '../core/selectors'
import type { Item, Phase, PhaseNumber } from '../core/types'

/** `null` is the entry that ignores phases — the one place a view spans the whole roadmap. */
export type PhaseSelection = PhaseNumber | null

/**
 * The phase picker shared by the backlog and the board. One component and not a
 * copy in each view, because the spec asks both surfaces to filter by phase the
 * same way, and two copies of "the same way" drift.
 */
export function PhaseSidebar({
  phases,
  items,
  selected,
  onSelect,
}: {
  phases: readonly Phase[]
  items: readonly Item[]
  selected: PhaseSelection
  onSelect: (phase: PhaseSelection) => void
}) {
  const done = items.filter((item) => item.state === 'done').length

  return (
    <aside className="phases">
      {phases.map((phase) => {
        const progress = phaseProgress(items, phase)
        return (
          <button
            key={phase.number}
            type="button"
            className={selected === phase.number ? 'phase-link active' : 'phase-link'}
            aria-pressed={selected === phase.number}
            onClick={() => onSelect(phase.number)}
          >
            <span className="phase-index">{phase.number}</span>
            <span className="phase-name">{phase.name}</span>
            <span className="phase-progress">
              {progress.done}/{progress.total}
            </span>
          </button>
        )
      })}

      <button
        type="button"
        className={selected === null ? 'phase-link active' : 'phase-link'}
        aria-pressed={selected === null}
        onClick={() => onSelect(null)}
      >
        <span className="phase-index">·</span>
        <span className="phase-name">All phases</span>
        <span className="phase-progress">
          {done}/{items.length}
        </span>
      </button>
    </aside>
  )
}

import { toEpochDay } from './dates'
import type { CivilDate, Item, Phase } from './types'

// Derived reads over the item list. Pure and platform-neutral, so the backlog,
// the board and the dashboard all answer the same question the same way — and
// `today` is always an argument, never a clock read.

export type ItemFilter = 'all' | 'pending' | 'in_progress' | 'overdue' | 'done'

export const ITEM_FILTERS: readonly ItemFilter[] = [
  'all',
  'pending',
  'in_progress',
  'overdue',
  'done',
] as const

/** Past its projected end and still not done. Today itself is not late yet. */
export function isOverdue(item: Item, today: CivilDate): boolean {
  return item.state !== 'done' && item.projectedEndDate < today
}

/** The projection has moved off the original plan. */
export function hasSlipped(item: Item): boolean {
  return (
    item.projectedStartDate !== item.baselineStartDate ||
    item.projectedEndDate !== item.baselineEndDate
  )
}

/** Days between the projected and the planned end. Positive is behind. */
export function slipDays(item: Item): number {
  return toEpochDay(item.projectedEndDate) - toEpochDay(item.baselineEndDate)
}

export function matchesFilter(item: Item, filter: ItemFilter, today: CivilDate): boolean {
  switch (filter) {
    case 'all':
      return true
    case 'overdue':
      return isOverdue(item, today)
    default:
      return item.state === filter
  }
}

export type PhaseGroup = {
  phase: Phase
  items: Item[]
}

/**
 * Items grouped by phase, in the curated dependency order rather than
 * alphabetically. Phases with nothing left after filtering are dropped.
 */
export function groupByPhase(items: readonly Item[], phases: readonly Phase[]): PhaseGroup[] {
  return phases
    .slice()
    .sort((a, b) => a.number - b.number)
    .map((phase) => ({
      phase,
      items: items
        .filter((item) => item.phase === phase.number)
        .sort((a, b) => a.sortOrder - b.sortOrder),
    }))
    .filter((group) => group.items.length > 0)
}

/** Done over total, per phase — the dashboard shows this as text, not a chart. */
export function phaseProgress(
  items: readonly Item[],
  phase: Phase,
): { done: number; total: number } {
  const inPhase = items.filter((item) => item.phase === phase.number)
  return {
    done: inPhase.filter((item) => item.state === 'done').length,
    total: inPhase.length,
  }
}

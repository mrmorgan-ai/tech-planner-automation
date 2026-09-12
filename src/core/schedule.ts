import {
  addStudyDays,
  firstStudyDayFrom,
  maxDate,
  minDate,
  studyDayAfter,
  studyDaysBetween,
  toCivilDate,
} from './dates'
import type { CivilDate, IsoDateTime, Item, ScheduleOptions, State } from './types'

/**
 * Dependency order, with ties broken by phase, then curated order, then id, so
 * the output is stable — a test comparing two runs compares the same order.
 */
export function topologicalOrder(items: readonly Item[]): Item[] {
  const byId = new Map(items.map((item) => [item.id, item]))

  for (const item of items) {
    for (const dependency of item.dependsOn) {
      if (!byId.has(dependency)) {
        throw new Error(`${item.id} depends on ${dependency}, which does not exist`)
      }
    }
  }

  const pending = new Map<string, number>(
    items.map((item) => [item.id, new Set(item.dependsOn).size]),
  )
  const dependents = new Map<string, string[]>(items.map((item) => [item.id, []]))
  for (const item of items) {
    for (const dependency of new Set(item.dependsOn)) {
      dependents.get(dependency)?.push(item.id)
    }
  }

  const ready = items
    .filter((item) => pending.get(item.id) === 0)
    .sort((a, b) => compareRank(rank(a), rank(b)))

  const ordered: Item[] = []
  while (ready.length > 0) {
    const next = ready.shift()
    if (!next) break
    ordered.push(next)

    for (const dependentId of dependents.get(next.id) ?? []) {
      const remaining = (pending.get(dependentId) ?? 0) - 1
      pending.set(dependentId, remaining)
      if (remaining === 0) {
        const dependent = byId.get(dependentId)
        if (dependent) insertByRank(ready, dependent)
      }
    }
  }

  if (ordered.length !== items.length) {
    const stuck = items
      .filter((item) => !ordered.includes(item))
      .map((item) => item.id)
      .join(', ')
    throw new Error(`The dependency graph has a cycle involving: ${stuck}`)
  }

  return ordered
}

/**
 * Recomputes `projectedStartDate`/`projectedEndDate` for every item from the
 * baselines, the dependency graph and whatever is already done.
 *
 * Deliberately a full recompute rather than propagation from the changed node:
 * with a roadmap this size it costs nothing, it is idempotent so projections
 * cannot drift, and it handles un-completing an item — which propagation does
 * not.
 */
export function recomputeProjections(items: readonly Item[], options: ScheduleOptions): Item[] {
  const { blackouts, timeZone } = options
  const projected = new Map<string, { start: CivilDate; end: CivilDate }>()

  for (const item of topologicalOrder(items)) {
    const duration = studyDaysBetween(item.baselineStartDate, item.baselineEndDate, blackouts)
    if (duration < 1) {
      throw new Error(
        `${item.id} has a baseline span with no study days: ${item.baselineStartDate}..${item.baselineEndDate}`,
      )
    }

    const latestDependencyEnd = item.dependsOn.reduce<CivilDate | null>((latest, id) => {
      const resolved = projected.get(id)
      if (!resolved) throw new Error(`${item.id} was projected before its dependency ${id}`)
      return latest === null || resolved.end > latest ? resolved.end : latest
    }, null)

    // The baseline is a floor: finishing early never pulls the rest forward.
    const earliest =
      latestDependencyEnd === null
        ? item.baselineStartDate
        : maxDate(item.baselineStartDate, studyDayAfter(latestDependencyEnd, blackouts))

    let start = firstStudyDayFrom(earliest, blackouts)
    let end: CivilDate

    if (item.state === 'done' && item.completedAt) {
      // A completed item freezes on its real date, whatever its dependencies do.
      end = toCivilDate(item.completedAt, timeZone)
      start = minDate(start, end)
    } else {
      end = addStudyDays(start, duration, blackouts)
    }

    projected.set(item.id, { start, end })
  }

  return items.map((item) => {
    const resolved = projected.get(item.id)
    if (!resolved) throw new Error(`${item.id} was not projected`)
    return {
      ...item,
      projectedStartDate: resolved.start,
      projectedEndDate: resolved.end,
    }
  })
}

/**
 * Moves one item to a new state and reprojects everything. Keeps the invariant
 * the schema enforces: `done` carries a `completedAt`, anything else does not.
 * Re-marking an item done keeps its original date.
 */
export function applyStateChange(
  items: readonly Item[],
  id: string,
  next: State,
  now: IsoDateTime,
  options: ScheduleOptions,
): Item[] {
  if (!items.some((item) => item.id === id)) throw new Error(`No item with id ${id}`)

  const updated = items.map((item) => {
    if (item.id !== id) return item
    return {
      ...item,
      state: next,
      completedAt: next === 'done' ? (item.completedAt ?? now) : null,
    }
  })

  return recomputeProjections(updated, options)
}

/**
 * Moves one item's baseline, then recomputes every projection from it.
 *
 * The baseline is the plan, so editing it is what makes the rest of the roadmap
 * follow: anything that depends on this item picks up the new end date through
 * the same rule as always, max(own baseline, dependency end + 1 study day). An
 * item that depends on nothing keeps its own dates, because nothing about its
 * plan changed.
 */
export function applyBaselineDates(
  items: readonly Item[],
  id: string,
  start: CivilDate,
  end: CivilDate,
  options: ScheduleOptions,
): Item[] {
  if (!items.some((item) => item.id === id)) throw new Error(`No item with id ${id}`)
  if (end < start) throw new Error(`End ${end} is before start ${start}`)

  const updated = items.map((item) =>
    item.id === id ? { ...item, baselineStartDate: start, baselineEndDate: end } : item,
  )

  return recomputeProjections(updated, options)
}

type Rank = readonly [number, number, string]

function rank(item: Item): Rank {
  return [item.phase, item.sortOrder, item.id]
}

function compareRank(a: Rank, b: Rank): number {
  return a[0] - b[0] || a[1] - b[1] || (a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0)
}

function insertByRank(queue: Item[], item: Item): void {
  const target = rank(item)
  const at = queue.findIndex((queued) => compareRank(rank(queued), target) > 0)
  if (at === -1) queue.push(item)
  else queue.splice(at, 0, item)
}

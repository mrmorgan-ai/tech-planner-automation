import { addDays, blackoutAt, startOfWeek, toCivilDate, toEpochDay } from './dates'
import { isOverdue } from './selectors'
import type { Blackout, CivilDate, Dimension, Item, Phase, Roadmap } from './types'

// The numbers behind the dashboard. Pure functions over the item list, so every
// block is a computation the tests can pin, not something the view improvises.

/**
 * Consecutive weeks with at least one item completed, counting back from the
 * current week. Only completing counts — starting something does not.
 *
 * The week in progress never breaks the streak: with nothing done yet this
 * week, counting starts at the previous one. Breaking it on Monday morning
 * would punish a week that has not had its chance.
 */
export function currentStreakWeeks(
  items: readonly Item[],
  today: CivilDate,
  timeZone: string,
): number {
  const weeks = new Set(
    items
      .filter((item) => item.state === 'done' && item.completedAt !== null)
      .map((item) => startOfWeek(toCivilDate(item.completedAt as string, timeZone))),
  )

  const thisWeek = startOfWeek(today)
  let cursor = weeks.has(thisWeek) ? thisWeek : addDays(thisWeek, -7)
  let streak = 0
  while (weeks.has(cursor)) {
    streak += 1
    cursor = addDays(cursor, -7)
  }
  return streak
}

/** Past due and not done, soonest first — the block is a to-do list, not a count. */
export function overdueItems(items: readonly Item[], today: CivilDate): Item[] {
  return items
    .filter((item) => isOverdue(item, today))
    .sort((a, b) => a.projectedEndDate.localeCompare(b.projectedEndDate))
}

export type MilestoneStatus = {
  item: Item
  /** Days from today to the projected end. Negative means it is already past. */
  daysAway: number
  /** Projected end minus baseline end. Positive is behind plan. */
  paceDays: number
}

/**
 * The nearest closing milestone still open. Read off `closingMilestoneId` and
 * never off `type`: one phase closes on a project task rather than on a
 * certification, so filtering by type would silently skip it.
 */
export function nextMilestone(
  items: readonly Item[],
  phases: readonly Phase[],
  today: CivilDate,
): MilestoneStatus | null {
  const ids = new Set(phases.map((phase) => phase.closingMilestoneId).filter(Boolean))
  const next = items
    .filter((item) => ids.has(item.id) && item.state !== 'done')
    .sort((a, b) => a.projectedEndDate.localeCompare(b.projectedEndDate))[0]

  if (!next) return null
  return {
    item: next,
    daysAway: toEpochDay(next.projectedEndDate) - toEpochDay(today),
    paceDays: toEpochDay(next.projectedEndDate) - toEpochDay(next.baselineEndDate),
  }
}

/** Where today sits: inside a non-study period, inside a phase, or past the end. */
export type Context =
  | { kind: 'blackout'; blackout: Blackout }
  | { kind: 'phase'; phase: Phase }
  | { kind: 'outside' }

export function activeContext(
  today: CivilDate,
  roadmap: Roadmap,
  items: readonly Item[],
): Context {
  const blackout = blackoutAt(today, roadmap.blackouts)
  if (blackout) return { kind: 'blackout', blackout }

  const phase = roadmap.phases.find((candidate) => {
    const range = phaseRange(items, candidate)
    return range !== null && range.start <= today && today <= range.end
  })
  return phase ? { kind: 'phase', phase } : { kind: 'outside' }
}

/** A phase spans its items: earliest projected start to latest projected end. */
export function phaseRange(
  items: readonly Item[],
  phase: Phase,
): { start: CivilDate; end: CivilDate } | null {
  const inPhase = items.filter((item) => item.phase === phase.number)
  if (inPhase.length === 0) return null
  return {
    start: inPhase.reduce((a, b) => (a < b.projectedStartDate ? a : b.projectedStartDate), inPhase[0]!.projectedStartDate),
    end: inPhase.reduce((a, b) => (a > b.projectedEndDate ? a : b.projectedEndDate), inPhase[0]!.projectedEndDate),
  }
}

/** What is in progress right now, soonest due first. The board's middle column. */
export function inProgress(items: readonly Item[]): Item[] {
  return items
    .filter((item) => item.state === 'in_progress')
    .sort((a, b) => a.projectedEndDate.localeCompare(b.projectedEndDate))
}

/**
 * Pending items with the nearest projected start. Shown when nothing is in
 * progress, as a suggestion of what to pick up — never as a restriction.
 */
export function suggestedNext(items: readonly Item[], limit = 3): Item[] {
  return items
    .filter((item) => item.state === 'pending')
    .sort((a, b) => a.projectedStartDate.localeCompare(b.projectedStartDate))
    .slice(0, limit)
}

/** Skills of every done item. Completing the item is the whole signal — no levels. */
export function coveredSkills(items: readonly Item[]): string[] {
  return unique(items.filter((item) => item.state === 'done').flatMap((item) => item.skills))
}

/** Skills still only reachable through unfinished items. */
export function pendingSkills(items: readonly Item[]): string[] {
  const covered = new Set(coveredSkills(items))
  return unique(
    items.filter((item) => item.state !== 'done').flatMap((item) => item.skills),
  ).filter((skill) => !covered.has(skill))
}

export type DimensionCoverage = {
  dimension: Dimension
  covered: number
  total: number
  /** Covered over total, 0 to 1. A dimension with no skills reads as 0. */
  ratio: number
}

/**
 * The radar, as numbers. An aggregation of the covered/pending split by
 * dimension — if that split is right, the radar is right.
 */
export function dimensionCoverage(items: readonly Item[], roadmap: Roadmap): DimensionCoverage[] {
  const covered = new Set(coveredSkills(items))
  const totals = new Map<Dimension, { covered: number; total: number }>(
    roadmap.dimensions.map((dimension) => [dimension, { covered: 0, total: 0 }]),
  )

  for (const [skill, dimension] of Object.entries(roadmap.skillDimension)) {
    const entry = totals.get(dimension)
    if (!entry) continue
    entry.total += 1
    if (covered.has(skill)) entry.covered += 1
  }

  return roadmap.dimensions.map((dimension) => {
    const entry = totals.get(dimension) ?? { covered: 0, total: 0 }
    return {
      dimension,
      covered: entry.covered,
      total: entry.total,
      ratio: entry.total === 0 ? 0 : entry.covered / entry.total,
    }
  })
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values)].sort((a, b) => a.localeCompare(b))
}

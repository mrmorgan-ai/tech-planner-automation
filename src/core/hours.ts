import { addDays, maxDate, minDate, startOfWeek, studyDaysBetween, toEpochDay } from './dates'
import type { Blackout, CivilDate, Item, WeeklyHours } from './types'

// Hours are read out of the `duration` text an item already carries, rather than
// stored as a number. The text is the honest record — "~25h, 7 videos" says more
// than 25 does — and an estimate that has to be kept in two places drifts.

const DURATION = /(\d+(?:[.,]\d+)?)\s*(?:[-–]\s*(\d+(?:[.,]\d+)?)\s*)?(h|hrs?|hours|min|minutes)\b/i

/**
 * The hours an item's duration text claims, or null when it claims none. A
 * range is read as its midpoint: "~2.5-3h" is 2.75.
 *
 * Returning null rather than 0 matters — a project task with no estimate is not
 * a task that takes no time, and a caller that wants to say so needs to see the
 * difference.
 */
export function estimatedHours(item: Item): number | null {
  const match = DURATION.exec(item.duration)
  if (!match) return null

  const low = Number(match[1]!.replace(',', '.'))
  const high = match[2] === undefined ? low : Number(match[2].replace(',', '.'))
  const value = (low + high) / 2
  return match[3]!.toLowerCase().startsWith('min') ? value / 60 : value
}

/** Hours across a list, ignoring what carries no estimate. */
export function sumHours(items: readonly Item[]): number {
  return items.reduce((total, item) => total + (estimatedHours(item) ?? 0), 0)
}

/** How many in a list have no estimate at all — what the sum above leaves out. */
export function withoutEstimate(items: readonly Item[]): number {
  return items.filter((item) => estimatedHours(item) === null).length
}

export type Week = {
  /** Monday. */
  from: CivilDate
  /** Sunday. */
  to: CivilDate
  /** Study hours available in this week, from the roadmap's own capacity. */
  hours: number
}

/**
 * The week a date falls in, with its capacity. The last week of a month is
 * shorter on purpose: it is the one the roadmap's owner reserves time in.
 */
export function weekOf(date: CivilDate, capacity: WeeklyHours): Week {
  const from = startOfWeek(date)
  return {
    from,
    to: addDays(from, 6),
    hours: isLastWeekOfMonth(from) ? capacity.lastWeekOfMonth : capacity.normal,
  }
}

/** True when no later Monday shares this one's month. */
export function isLastWeekOfMonth(monday: CivilDate): boolean {
  return addDays(monday, 7).slice(0, 7) !== monday.slice(0, 7)
}

/** Items whose projection touches the week at all, not only those starting in it. */
export function inWeek(items: readonly Item[], week: Week): Item[] {
  return items.filter(
    (item) => item.projectedStartDate <= week.to && item.projectedEndDate >= week.from,
  )
}

/**
 * The hours of a list that fall inside one week, spread across each item's own
 * study days.
 *
 * Counting a whole estimate in every week it touches is what makes a weekly
 * figure meaningless: a 25h course spanning four weeks is not 25h of work in
 * each of them. An item with no estimate contributes nothing, same as anywhere
 * else.
 */
export function hoursInWeek(
  items: readonly Item[],
  week: Week,
  blackouts: readonly Blackout[],
): number {
  return items.reduce((total, item) => {
    const hours = estimatedHours(item)
    if (hours === null) return total

    const span = studyDaysBetween(item.projectedStartDate, item.projectedEndDate, blackouts)
    if (span === 0) return total

    const from = maxDate(item.projectedStartDate, week.from)
    const to = minDate(item.projectedEndDate, week.to)
    if (to < from) return total

    return total + (hours * studyDaysBetween(from, to, blackouts)) / span
  }, 0)
}

/** Days of a week that are already behind, so "hours left" can mean something. */
export function daysLeftInWeek(week: Week, today: CivilDate): number {
  if (today < week.from) return 7
  if (today > week.to) return 0
  return toEpochDay(week.to) - toEpochDay(today) + 1
}

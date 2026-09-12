import type { Blackout, CivilDate, IsoDateTime } from './types'

const MS_PER_DAY = 86_400_000
const CIVIL_DATE = /^\d{4}-\d{2}-\d{2}$/

// ISO dates compare chronologically as plain strings, so `<` and `>` are the
// comparison operators throughout this module. No Date objects involved.
//
// Blackouts are always passed in: they are roadmap content, so there is no
// default for them to fall back on.

export function isCivilDate(value: string): boolean {
  return CIVIL_DATE.test(value)
}

export function toEpochDay(date: CivilDate): number {
  if (!isCivilDate(date)) throw new Error(`Not a civil date: ${date}`)
  const parts = date.split('-')
  const year = Number(parts[0])
  const month = Number(parts[1])
  const day = Number(parts[2])
  return Date.UTC(year, month - 1, day) / MS_PER_DAY
}

export function fromEpochDay(day: number): CivilDate {
  return new Date(day * MS_PER_DAY).toISOString().slice(0, 10)
}

export function addDays(date: CivilDate, days: number): CivilDate {
  return fromEpochDay(toEpochDay(date) + days)
}

export function maxDate(first: CivilDate, ...rest: CivilDate[]): CivilDate {
  return rest.reduce((best, candidate) => (candidate > best ? candidate : best), first)
}

export function minDate(first: CivilDate, ...rest: CivilDate[]): CivilDate {
  return rest.reduce((best, candidate) => (candidate < best ? candidate : best), first)
}

/** The non-study period covering this date, if any. */
export function blackoutAt(date: CivilDate, blackouts: readonly Blackout[]): Blackout | null {
  return blackouts.find((period) => date >= period.from && date <= period.to) ?? null
}

export function isBlackoutDay(date: CivilDate, blackouts: readonly Blackout[]): boolean {
  return blackoutAt(date, blackouts) !== null
}

/**
 * The first study day on or after `date`. Used when a projected start lands
 * inside a blackout: it is pushed to the first day after it.
 */
export function firstStudyDayFrom(date: CivilDate, blackouts: readonly Blackout[]): CivilDate {
  let cursor = date
  for (;;) {
    const period = blackoutAt(cursor, blackouts)
    if (!period) return cursor
    cursor = addDays(period.to, 1)
  }
}

/**
 * The next study day strictly after `date`. This is the dependency handoff: an
 * item starts the day after the one it depends on ends, never the same day.
 */
export function studyDayAfter(date: CivilDate, blackouts: readonly Blackout[]): CivilDate {
  return firstStudyDayFrom(addDays(date, 1), blackouts)
}

/**
 * The `days`-th study day counting `start` as the first — so a span of one day
 * ends on the day it starts. Skips blackouts without consuming duration.
 */
export function addStudyDays(
  start: CivilDate,
  days: number,
  blackouts: readonly Blackout[],
): CivilDate {
  if (!Number.isInteger(days) || days < 1) {
    throw new Error(`A span needs at least one study day, got ${days}`)
  }
  let cursor = firstStudyDayFrom(start, blackouts)
  for (let counted = 1; counted < days; counted++) {
    cursor = studyDayAfter(cursor, blackouts)
  }
  return cursor
}

/** Study days in `[from, to]`, both ends included. Zero if the range is empty. */
export function studyDaysBetween(
  from: CivilDate,
  to: CivilDate,
  blackouts: readonly Blackout[],
): number {
  if (to < from) return 0
  const total = toEpochDay(to) - toEpochDay(from) + 1
  let blacked = 0
  for (const period of blackouts) {
    const start = maxDate(from, period.from)
    const end = minDate(to, period.to)
    if (start <= end) blacked += toEpochDay(end) - toEpochDay(start) + 1
  }
  return total - blacked
}

const formatters = new Map<string, Intl.DateTimeFormat>()

function civilDateFormatter(timeZone: string): Intl.DateTimeFormat {
  const cached = formatters.get(timeZone)
  if (cached) return cached
  // `en-CA` formats as YYYY-MM-DD, which is exactly the civil-date shape.
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  formatters.set(timeZone, formatter)
  return formatter
}

/**
 * The civil date an instant falls on, in the roadmap's timezone. Pure: it reads
 * its input, never the clock — that is `src/server/clock.ts`'s job.
 */
export function toCivilDate(instant: IsoDateTime | Date, timeZone: string): CivilDate {
  const date = instant instanceof Date ? instant : new Date(instant)
  if (Number.isNaN(date.getTime())) throw new Error(`Not an instant: ${String(instant)}`)
  return civilDateFormatter(timeZone).format(date)
}

/**
 * The Monday of the week a date falls in. Weeks are the unit the streak counts
 * in, and Monday is where a study week starts for the roadmap's owner.
 */
export function startOfWeek(date: CivilDate): CivilDate {
  const day = toEpochDay(date)
  // Epoch day 0 is a Thursday, so +3 puts Monday at a multiple of 7.
  return fromEpochDay(day - ((day + 3) % 7))
}

/** An unbroken run of study days. */
export type Segment = { from: CivilDate; to: CivilDate }

/**
 * A date range split into the stretches that are actually study days, dropping
 * the declared pauses in between.
 *
 * The engine already skips pauses when it counts a duration, so a bar drawn as
 * one rectangle from start to end claims work happens on days the plan says
 * nothing happens. These are the pieces to draw instead.
 */
export function studySegments(
  from: CivilDate,
  to: CivilDate,
  blackouts: readonly Blackout[],
): Segment[] {
  const segments: Segment[] = []
  let open: Segment | null = null

  for (let day = toEpochDay(from); day <= toEpochDay(to); day += 1) {
    const date = fromEpochDay(day)
    if (isBlackoutDay(date, blackouts)) {
      if (open) segments.push(open)
      open = null
    } else if (open) {
      open.to = date
    } else {
      open = { from: date, to: date }
    }
  }

  if (open) segments.push(open)
  return segments
}

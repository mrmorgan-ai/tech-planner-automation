import { toCivilDate } from '../core/dates'
import type { CivilDate, IsoDateTime } from '../core/types'

/**
 * The only place in the app that reads the wall clock. Everything downstream
 * takes the result as an argument, which is what makes `src/core/` testable
 * with fixtures — it never calls `new Date()`.
 */
export function nowIso(now: Date = new Date()): IsoDateTime {
  return now.toISOString()
}

/** Today's date in the roadmap's timezone, which comes from the database. */
export function todayIn(timeZone: string, now: Date = new Date()): CivilDate {
  return toCivilDate(now, timeZone)
}

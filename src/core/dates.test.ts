import { describe, expect, it } from 'vitest'
import {
  addDays,
  addStudyDays,
  blackoutAt,
  firstStudyDayFrom,
  fromEpochDay,
  isBlackoutDay,
  startOfWeek,
  studyDayAfter,
  studyDaysBetween,
  toCivilDate,
  toEpochDay,
} from './dates'
import type { Blackout } from './types'

// A synthetic calendar. The real roadmap's periods are content and live in the
// database; the real ones are checked by the seed validator instead.
const BREAK: Blackout[] = [{ from: '2030-01-15', to: '2030-01-28', reason: 'Break' }]

describe('civil date arithmetic', () => {
  it('round-trips through epoch days', () => {
    expect(fromEpochDay(toEpochDay('2030-01-08'))).toBe('2030-01-08')
  })

  it('crosses month and year boundaries', () => {
    expect(addDays('2030-01-31', 1)).toBe('2030-02-01')
    expect(addDays('2030-12-31', 1)).toBe('2031-01-01')
    expect(addDays('2032-03-01', -1)).toBe('2032-02-29')
  })

  it('rejects anything that is not YYYY-MM-DD', () => {
    expect(() => toEpochDay('08/01/2030')).toThrow()
  })
})

describe('blackout periods', () => {
  it('includes both ends of the range', () => {
    expect(isBlackoutDay('2030-01-14', BREAK)).toBe(false)
    expect(isBlackoutDay('2030-01-15', BREAK)).toBe(true)
    expect(isBlackoutDay('2030-01-28', BREAK)).toBe(true)
    expect(isBlackoutDay('2030-01-29', BREAK)).toBe(false)
  })

  it('names the reason, for the dashboard to show instead of a phase', () => {
    expect(blackoutAt('2030-01-20', BREAK)?.reason).toBe('Break')
    expect(blackoutAt('2030-01-29', BREAK)).toBeNull()
  })
})

describe('firstStudyDayFrom vs studyDayAfter', () => {
  it('firstStudyDayFrom keeps a date that is already a study day', () => {
    expect(firstStudyDayFrom('2030-01-14', BREAK)).toBe('2030-01-14')
  })

  it('firstStudyDayFrom pushes out of a blackout', () => {
    expect(firstStudyDayFrom('2030-01-20', BREAK)).toBe('2030-01-29')
  })

  it('studyDayAfter always moves, and skips a blackout entirely', () => {
    expect(studyDayAfter('2030-01-08', BREAK)).toBe('2030-01-09')
    expect(studyDayAfter('2030-01-14', BREAK)).toBe('2030-01-29')
  })
})

describe('addStudyDays', () => {
  it('counts the start day as the first', () => {
    expect(addStudyDays('2030-01-08', 1, BREAK)).toBe('2030-01-08')
    expect(addStudyDays('2030-01-08', 7, BREAK)).toBe('2030-01-14')
  })

  it('skips blackouts without spending duration on them', () => {
    // Jan 8-14 is 7 days; the remaining 7 resume on Jan 29.
    expect(addStudyDays('2030-01-08', 14, BREAK)).toBe('2030-02-04')
  })

  it('refuses a span of zero days', () => {
    expect(() => addStudyDays('2030-01-08', 0, BREAK)).toThrow()
  })
})

describe('studyDaysBetween', () => {
  it('includes both ends', () => {
    expect(studyDaysBetween('2030-01-08', '2030-01-14', BREAK)).toBe(7)
    expect(studyDaysBetween('2030-01-08', '2030-01-08', BREAK)).toBe(1)
  })

  it('excludes blackout days', () => {
    // 28 calendar days minus the 14 of the break.
    expect(studyDaysBetween('2030-01-08', '2030-02-04', BREAK)).toBe(14)
  })

  it('is the inverse of addStudyDays across a blackout', () => {
    const duration = studyDaysBetween('2030-01-08', '2030-02-04', BREAK)
    expect(addStudyDays('2030-01-08', duration, BREAK)).toBe('2030-02-04')
  })

  it('ignores blackouts entirely when there are none', () => {
    expect(studyDaysBetween('2030-01-08', '2030-02-04', [])).toBe(28)
  })
})

describe('toCivilDate', () => {
  it('resolves an instant to its local date, not its UTC date', () => {
    // 03:00 UTC is still 22:00 the previous day at UTC-5.
    expect(toCivilDate('2030-01-09T03:00:00Z', 'America/New_York')).toBe('2030-01-08')
    expect(toCivilDate('2030-01-08T18:00:00-05:00', 'America/New_York')).toBe('2030-01-08')
  })

  it('reads UTC as UTC', () => {
    expect(toCivilDate('2030-01-09T03:00:00Z', 'UTC')).toBe('2030-01-09')
  })
})

describe('startOfWeek', () => {
  it('returns the Monday of that week', () => {
    // 2030-02-06 is a Wednesday; its week starts on Monday 2030-02-04.
    expect(startOfWeek('2030-02-06')).toBe('2030-02-04')
  })

  it('leaves a Monday where it is', () => {
    expect(startOfWeek('2030-02-04')).toBe('2030-02-04')
  })

  it('keeps Sunday in the week that started six days earlier', () => {
    expect(startOfWeek('2030-02-10')).toBe('2030-02-04')
  })
})

import { describe, expect, it } from 'vitest'
import {
  daysLeftInWeek,
  estimatedHours,
  hoursInWeek,
  inWeek,
  isLastWeekOfMonth,
  sumHours,
  weekOf,
  withoutEstimate,
} from './hours'
import type { Item, WeeklyHours } from './types'

function item(id: string, overrides: Partial<Item> = {}): Item {
  return {
    id,
    name: id,
    type: 'Course',
    phase: 1,
    skills: [],
    baselineStartDate: '2030-02-04',
    baselineEndDate: '2030-02-10',
    projectedStartDate: '2030-02-04',
    projectedEndDate: '2030-02-10',
    dependsOn: [],
    price: '',
    link: null,
    resources: [],
    duration: '',
    notes: '',
    state: 'pending',
    completedAt: null,
    sortOrder: 1,
    ...overrides,
  }
}

const CAPACITY: WeeklyHours = { normal: 15, lastWeekOfMonth: 10 }

describe('estimatedHours', () => {
  it('reads plain hours', () => {
    expect(estimatedHours(item('a', { duration: '~10h' }))).toBe(10)
  })

  it('reads a decimal', () => {
    expect(estimatedHours(item('a', { duration: '~1.5h' }))).toBe(1.5)
  })

  it('reads a range as its midpoint', () => {
    expect(estimatedHours(item('a', { duration: '~2.5-3h' }))).toBe(2.75)
  })

  it('converts minutes', () => {
    expect(estimatedHours(item('a', { duration: '~45 min' }))).toBe(0.75)
  })

  it('ignores what follows the hours', () => {
    expect(estimatedHours(item('a', { duration: '~25h, 7 videos' }))).toBe(25)
  })

  it('is null when the text carries no hours', () => {
    expect(estimatedHours(item('a', { duration: '7 videos' }))).toBeNull()
    expect(estimatedHours(item('a', { duration: 'complete' }))).toBeNull()
    expect(estimatedHours(item('a', { duration: '' }))).toBeNull()
  })

  it('is null and not zero, so a missing estimate is distinguishable', () => {
    const missing = item('a')

    expect(estimatedHours(missing)).not.toBe(0)
    expect(estimatedHours(missing)).toBeNull()
  })
})

describe('sumHours and withoutEstimate', () => {
  const items = [
    item('a', { duration: '~10h' }),
    item('b', { duration: '~30 min' }),
    item('c'),
    item('d', { duration: 'complete' }),
  ]

  it('adds what is estimated', () => {
    expect(sumHours(items)).toBe(10.5)
  })

  it('counts what the sum leaves out', () => {
    expect(withoutEstimate(items)).toBe(2)
  })

  it('is zero on an empty list', () => {
    expect(sumHours([])).toBe(0)
  })
})

describe('isLastWeekOfMonth', () => {
  it('is the last week when the next Monday is a new month', () => {
    // 2030-04-29 is a Monday; the next Monday is 2030-05-06.
    expect(isLastWeekOfMonth('2030-04-29')).toBe(true)
  })

  it('is not the last week mid-month', () => {
    expect(isLastWeekOfMonth('2030-04-08')).toBe(false)
  })

  it('is the last week when the next Monday is a new year', () => {
    expect(isLastWeekOfMonth('2030-12-30')).toBe(true)
  })
})

describe('weekOf', () => {
  it('spans Monday to Sunday with the normal capacity', () => {
    expect(weekOf('2030-02-06', CAPACITY)).toEqual({
      from: '2030-02-04',
      to: '2030-02-10',
      hours: 15,
    })
  })

  it('uses the reduced capacity in the last week of a month', () => {
    expect(weekOf('2030-04-30', CAPACITY).hours).toBe(10)
  })
})

describe('inWeek', () => {
  const week = weekOf('2030-02-06', CAPACITY)

  it('includes an item that merely overlaps the week', () => {
    const spanning = item('long', {
      projectedStartDate: '2030-01-28',
      projectedEndDate: '2030-02-20',
    })

    expect(inWeek([spanning], week).map((entry) => entry.id)).toEqual(['long'])
  })

  it('excludes an item that ends before the week starts', () => {
    const before = item('before', {
      projectedStartDate: '2030-01-21',
      projectedEndDate: '2030-02-03',
    })

    expect(inWeek([before], week)).toEqual([])
  })

  it('excludes an item that starts after the week ends', () => {
    const after = item('after', {
      projectedStartDate: '2030-02-11',
      projectedEndDate: '2030-02-15',
    })

    expect(inWeek([after], week)).toEqual([])
  })
})

describe('daysLeftInWeek', () => {
  const week = weekOf('2030-02-06', CAPACITY)

  it('counts today as still available', () => {
    expect(daysLeftInWeek(week, '2030-02-10')).toBe(1)
  })

  it('is the whole week before it starts', () => {
    expect(daysLeftInWeek(week, '2030-01-30')).toBe(7)
  })

  it('is nothing once the week is over', () => {
    expect(daysLeftInWeek(week, '2030-02-11')).toBe(0)
  })

  it('counts from Monday', () => {
    expect(daysLeftInWeek(week, '2030-02-04')).toBe(7)
  })
})

describe('hoursInWeek', () => {
  const week = weekOf('2030-02-06', CAPACITY)

  it('counts only the share of a multi-week item that falls in the week', () => {
    // 2030-01-28 to 2030-02-24 is 28 days, and 7 of them are this week.
    const long = item('long', {
      duration: '~28h',
      projectedStartDate: '2030-01-28',
      projectedEndDate: '2030-02-24',
    })

    expect(hoursInWeek([long], week, [])).toBeCloseTo(7)
  })

  it('counts all of an item that fits inside the week', () => {
    const inside = item('inside', {
      duration: '~6h',
      projectedStartDate: '2030-02-05',
      projectedEndDate: '2030-02-08',
    })

    expect(hoursInWeek([inside], week, [])).toBeCloseTo(6)
  })

  it('ignores an item outside the week', () => {
    const outside = item('outside', {
      duration: '~10h',
      projectedStartDate: '2030-02-11',
      projectedEndDate: '2030-02-15',
    })

    expect(hoursInWeek([outside], week, [])).toBe(0)
  })

  it('ignores an item with no estimate', () => {
    const vague = item('vague', {
      projectedStartDate: '2030-02-05',
      projectedEndDate: '2030-02-08',
    })

    expect(hoursInWeek([vague], week, [])).toBe(0)
  })

  it('skips the non-study days inside the week', () => {
    // The whole of this week is a blackout, so none of the item lands in it.
    const blackouts = [{ from: '2030-02-04', to: '2030-02-10', reason: 'Break' }]
    const spanning = item('spanning', {
      duration: '~10h',
      projectedStartDate: '2030-02-01',
      projectedEndDate: '2030-02-15',
    })

    expect(hoursInWeek([spanning], week, blackouts)).toBe(0)
  })

  it('never counts more than the item estimates', () => {
    const exact = item('exact', {
      duration: '~9h',
      projectedStartDate: '2030-02-04',
      projectedEndDate: '2030-02-10',
    })

    expect(hoursInWeek([exact], week, [])).toBeCloseTo(9)
  })
})

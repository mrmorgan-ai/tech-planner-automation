import { describe, expect, it } from 'vitest'
import {
  groupByPhase,
  hasSlipped,
  isOverdue,
  matchesFilter,
  phaseProgress,
  slipDays,
} from './selectors'
import type { Item, Phase } from './types'

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
    notes: '',
    state: 'pending',
    completedAt: null,
    sortOrder: 1,
    ...overrides,
  }
}

const phases: Phase[] = [
  { number: 1, name: 'First', closingMilestoneId: null },
  { number: 2, name: 'Second', closingMilestoneId: null },
]

describe('isOverdue', () => {
  it('is not overdue on the day it is due', () => {
    expect(isOverdue(item('a'), '2030-02-10')).toBe(false)
  })

  it('is overdue the day after', () => {
    expect(isOverdue(item('a'), '2030-02-11')).toBe(true)
  })

  it('is never overdue once done, however late it was', () => {
    const done = item('a', { state: 'done', completedAt: '2030-03-01T12:00:00Z' })
    expect(isOverdue(done, '2030-06-01')).toBe(false)
  })

  it('counts an item in progress past its date', () => {
    expect(isOverdue(item('a', { state: 'in_progress' }), '2030-02-11')).toBe(true)
  })
})

describe('slip', () => {
  it('reports no slip when the projection sits on the plan', () => {
    expect(hasSlipped(item('a'))).toBe(false)
    expect(slipDays(item('a'))).toBe(0)
  })

  it('counts days behind as positive', () => {
    const late = item('a', { projectedStartDate: '2030-02-11', projectedEndDate: '2030-02-17' })
    expect(hasSlipped(late)).toBe(true)
    expect(slipDays(late)).toBe(7)
  })

  it('counts days ahead as negative', () => {
    const early = item('a', { projectedEndDate: '2030-02-05' })
    expect(slipDays(early)).toBe(-5)
  })
})

describe('matchesFilter', () => {
  const today = '2030-02-11'

  it('lets everything through on all', () => {
    expect(matchesFilter(item('a'), 'all', today)).toBe(true)
  })

  it('matches on the state field for the three state filters', () => {
    expect(matchesFilter(item('a', { state: 'in_progress' }), 'in_progress', today)).toBe(true)
    expect(matchesFilter(item('a', { state: 'in_progress' }), 'pending', today)).toBe(false)
    expect(
      matchesFilter(item('a', { state: 'done', completedAt: '2030-02-01T00:00:00Z' }), 'done', today),
    ).toBe(true)
  })

  it('treats overdue as a computed filter, not a state', () => {
    expect(matchesFilter(item('a'), 'overdue', today)).toBe(true)
    expect(matchesFilter(item('a'), 'overdue', '2030-02-01')).toBe(false)
  })
})

describe('groupByPhase', () => {
  it('orders phases by number and items by their curated order', () => {
    const items = [
      item('second', { phase: 1, sortOrder: 2 }),
      item('first', { phase: 1, sortOrder: 1 }),
      item('later', { phase: 2, sortOrder: 1 }),
    ]
    const groups = groupByPhase(items, phases)
    expect(groups.map((group) => group.phase.number)).toEqual([1, 2])
    expect(groups[0]?.items.map((entry) => entry.id)).toEqual(['first', 'second'])
  })

  it('drops a phase with nothing left in it', () => {
    const groups = groupByPhase([item('only', { phase: 2 })], phases)
    expect(groups).toHaveLength(1)
    expect(groups[0]?.phase.number).toBe(2)
  })
})

describe('phaseProgress', () => {
  it('counts done over total for one phase only', () => {
    const items = [
      item('a', { phase: 1, state: 'done', completedAt: '2030-02-01T00:00:00Z' }),
      item('b', { phase: 1 }),
      item('c', { phase: 2, state: 'done', completedAt: '2030-02-01T00:00:00Z' }),
    ]
    expect(phaseProgress(items, phases[0] as Phase)).toEqual({ done: 1, total: 2 })
  })
})

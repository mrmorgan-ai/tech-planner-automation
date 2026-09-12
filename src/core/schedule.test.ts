import { describe, expect, it } from 'vitest'
import { applyBaselineDates, applyStateChange, recomputeProjections, topologicalOrder } from './schedule'
import type { Blackout, Item, ScheduleOptions } from './types'

// A synthetic calendar and timezone: the real ones are roadmap content and live
// in the database.
const BREAK: Blackout[] = [{ from: '2030-01-15', to: '2030-01-28', reason: 'Break' }]
const OPTIONS: ScheduleOptions = { blackouts: BREAK, timeZone: 'America/New_York' }

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
    sortOrder: 0,
    ...overrides,
  }
}

/** Four one-week items in a straight chain, on consecutive weeks. */
function chain(): Item[] {
  return [
    item('a', { baselineStartDate: '2030-02-04', baselineEndDate: '2030-02-10', sortOrder: 1 }),
    item('b', {
      baselineStartDate: '2030-02-11',
      baselineEndDate: '2030-02-17',
      dependsOn: ['a'],
      sortOrder: 2,
    }),
    item('c', {
      baselineStartDate: '2030-02-18',
      baselineEndDate: '2030-02-24',
      dependsOn: ['b'],
      sortOrder: 3,
    }),
    item('d', {
      baselineStartDate: '2030-02-25',
      baselineEndDate: '2030-03-03',
      dependsOn: ['c'],
      sortOrder: 4,
    }),
  ]
}

function find(items: Item[], id: string): Item {
  const found = items.find((candidate) => candidate.id === id)
  if (!found) throw new Error(`No fixture item ${id}`)
  return found
}

describe('untouched plan', () => {
  it('projects every item onto its own baseline', () => {
    for (const projected of recomputeProjections(chain(), OPTIONS)) {
      expect(projected.projectedStartDate).toBe(projected.baselineStartDate)
      expect(projected.projectedEndDate).toBe(projected.baselineEndDate)
    }
  })

  it('is idempotent', () => {
    const once = recomputeProjections(chain(), OPTIONS)
    expect(recomputeProjections(once, OPTIONS)).toEqual(once)
  })
})

describe('a chain of four items', () => {
  const result = applyStateChange(chain(), 'a', 'done', '2030-02-17T18:00:00-05:00', OPTIONS)

  it('freezes the completed item on its real date', () => {
    expect(find(result, 'a').projectedEndDate).toBe('2030-02-17')
  })

  it('starts the next item the day after, never the same day', () => {
    expect(find(result, 'b').projectedStartDate).toBe('2030-02-18')
  })

  it('drags the whole chain by the same week', () => {
    expect(find(result, 'b').projectedEndDate).toBe('2030-02-24')
    expect(find(result, 'c').projectedStartDate).toBe('2030-02-25')
    expect(find(result, 'd').projectedEndDate).toBe('2030-03-10')
  })

  it('preserves each planned duration instead of stretching it', () => {
    for (const projected of result) {
      if (projected.state === 'done') continue
      const days =
        (new Date(projected.projectedEndDate).getTime() -
          new Date(projected.projectedStartDate).getTime()) /
        86_400_000
      expect(days).toBe(6)
    }
  })
})

describe('a closing milestone with five predecessors', () => {
  const items = [
    ...['p1', 'p2', 'p3', 'p4', 'p5'].map((id, index) =>
      item(id, {
        baselineStartDate: '2030-02-04',
        baselineEndDate: '2030-02-10',
        sortOrder: index + 1,
      }),
    ),
    item('milestone', {
      type: 'Certification',
      baselineStartDate: '2030-02-11',
      baselineEndDate: '2030-02-17',
      dependsOn: ['p1', 'p2', 'p3', 'p4', 'p5'],
      sortOrder: 6,
    }),
  ]

  it('waits for the latest predecessor, not the first', () => {
    const result = applyStateChange(items, 'p3', 'done', '2030-02-19T12:00:00-05:00', OPTIONS)
    expect(find(result, 'milestone').projectedStartDate).toBe('2030-02-20')
    expect(find(result, 'milestone').projectedEndDate).toBe('2030-02-26')
  })

  it('does not move when a predecessor lands on time', () => {
    const result = applyStateChange(items, 'p3', 'done', '2030-02-10T12:00:00-05:00', OPTIONS)
    expect(find(result, 'milestone').projectedStartDate).toBe('2030-02-11')
  })
})

describe('completing out of order', () => {
  it('freezes an item completed before its own window, and never moves it again', () => {
    const early = applyStateChange(chain(), 'c', 'done', '2030-02-05T12:00:00-05:00', OPTIONS)
    expect(find(early, 'c').projectedEndDate).toBe('2030-02-05')
    // The bar cannot end before it starts — the schema's CHECK relies on this.
    expect(find(early, 'c').projectedStartDate).toBe('2030-02-05')

    const thenLate = applyStateChange(early, 'a', 'done', '2030-02-17T18:00:00-05:00', OPTIONS)
    expect(find(thenLate, 'c').projectedEndDate).toBe('2030-02-05')
    expect(find(thenLate, 'b').projectedEndDate).toBe('2030-02-24')
  })

  it('passes propagation through a completed item using its real date', () => {
    const items = chain().map((candidate) =>
      candidate.id === 'c'
        ? { ...candidate, state: 'done' as const, completedAt: '2030-03-10T12:00:00-05:00' }
        : candidate,
    )
    const result = recomputeProjections(items, OPTIONS)
    expect(find(result, 'c').projectedEndDate).toBe('2030-03-10')
    expect(find(result, 'd').projectedStartDate).toBe('2030-03-11')
  })
})

describe('finishing early', () => {
  it('does not pull the rest of the plan forward', () => {
    const result = applyStateChange(chain(), 'a', 'done', '2030-02-06T12:00:00-05:00', OPTIONS)
    expect(find(result, 'b').projectedStartDate).toBe('2030-02-11')
    expect(find(result, 'd').projectedEndDate).toBe('2030-03-03')
  })
})

describe('blackout periods', () => {
  const items = [
    item('x', { baselineStartDate: '2030-01-01', baselineEndDate: '2030-01-07', sortOrder: 1 }),
    item('y', {
      baselineStartDate: '2030-01-08',
      baselineEndDate: '2030-01-14',
      dependsOn: ['x'],
      sortOrder: 2,
    }),
    item('z', {
      baselineStartDate: '2030-01-29',
      baselineEndDate: '2030-02-04',
      dependsOn: ['y'],
      sortOrder: 3,
    }),
  ]

  it('pushes a start that lands inside a blackout to the first day after it', () => {
    const result = applyStateChange(items, 'x', 'done', '2030-01-14T12:00:00-05:00', OPTIONS)
    expect(find(result, 'y').projectedStartDate).toBe('2030-01-29')
    expect(find(result, 'y').projectedEndDate).toBe('2030-02-04')
  })

  it('lets a span straddle a blackout without spending duration inside it', () => {
    const result = applyStateChange(items, 'x', 'done', '2030-01-11T12:00:00-05:00', OPTIONS)
    expect(find(result, 'y').projectedStartDate).toBe('2030-01-12')
    // 3 study days before the break, the remaining 4 after it.
    expect(find(result, 'y').projectedEndDate).toBe('2030-02-01')
    expect(find(result, 'z').projectedStartDate).toBe('2030-02-02')
  })
})

describe('un-completing an item', () => {
  it('releases the chain and clears the completion date', () => {
    const done = applyStateChange(chain(), 'a', 'done', '2030-02-17T18:00:00-05:00', OPTIONS)
    expect(find(done, 'b').projectedStartDate).toBe('2030-02-18')

    const undone = applyStateChange(done, 'a', 'pending', '2030-02-18T10:00:00-05:00', OPTIONS)
    expect(find(undone, 'a').completedAt).toBeNull()
    expect(find(undone, 'a').projectedEndDate).toBe('2030-02-10')
    expect(find(undone, 'b').projectedStartDate).toBe('2030-02-11')
  })

  it('keeps the original date when an item is marked done twice', () => {
    const first = applyStateChange(chain(), 'a', 'done', '2030-02-17T18:00:00-05:00', OPTIONS)
    const again = applyStateChange(first, 'a', 'done', '2030-02-25T09:00:00-05:00', OPTIONS)
    expect(find(again, 'a').completedAt).toBe('2030-02-17T18:00:00-05:00')
  })
})

describe('graph validation', () => {
  it('refuses a cycle instead of looping forever', () => {
    const items = [item('a', { dependsOn: ['b'] }), item('b', { dependsOn: ['a'] })]
    expect(() => recomputeProjections(items, OPTIONS)).toThrow(/cycle/i)
  })

  it('refuses a dependency that does not exist', () => {
    expect(() => topologicalOrder([item('a', { dependsOn: ['ghost'] })])).toThrow(/ghost/)
  })

  it('orders dependencies before dependents', () => {
    const ordered = topologicalOrder(chain().slice().reverse()).map((candidate) => candidate.id)
    expect(ordered).toEqual(['a', 'b', 'c', 'd'])
  })
})

describe('applyBaselineDates', () => {
  // Dates deliberately before the fixture's break (2030-01-15 to 01-28), so
  // these cases measure the handoff and nothing else. The break has its own
  // case at the end.
  const chain = [
    item('first', { baselineStartDate: '2030-01-07', baselineEndDate: '2030-01-08', sortOrder: 1 }),
    item('second', {
      baselineStartDate: '2030-01-09',
      baselineEndDate: '2030-01-11',
      dependsOn: ['first'],
      sortOrder: 2,
    }),
  ]

  it('writes the new baseline on the item it names', () => {
    const after = applyBaselineDates(chain, 'first', '2030-01-07', '2030-01-10', OPTIONS)

    const first = after.find((entry) => entry.id === 'first')!
    expect([first.baselineStartDate, first.baselineEndDate]).toEqual(['2030-01-07', '2030-01-10'])
  })

  it('pushes what depends on it to the next study day', () => {
    const after = applyBaselineDates(chain, 'first', '2030-01-07', '2030-01-10', OPTIONS)

    const second = after.find((entry) => entry.id === 'second')!
    expect(second.projectedStartDate).toBe('2030-01-11')
    // The dependent's own plan did not change, only its projection.
    expect(second.baselineStartDate).toBe('2030-01-09')
  })

  it('leaves an item that depends on nothing where it was', () => {
    const loose = [
      ...chain,
      item('loose', {
        baselineStartDate: '2030-01-09',
        baselineEndDate: '2030-01-10',
        sortOrder: 3,
      }),
    ]

    const after = applyBaselineDates(loose, 'first', '2030-01-07', '2030-01-10', OPTIONS)

    const untouched = after.find((entry) => entry.id === 'loose')!
    expect(untouched.projectedStartDate).toBe('2030-01-09')
  })

  it('pulls a dependent back when the baseline shrinks again', () => {
    const stretched = applyBaselineDates(chain, 'first', '2030-01-07', '2030-01-10', OPTIONS)
    const shrunk = applyBaselineDates(stretched, 'first', '2030-01-07', '2030-01-08', OPTIONS)

    expect(shrunk.find((entry) => entry.id === 'second')!.projectedStartDate).toBe('2030-01-09')
  })

  it('hands off across a non-study period instead of into it', () => {
    const after = applyBaselineDates(chain, 'first', '2030-01-07', '2030-01-14', OPTIONS)

    expect(after.find((entry) => entry.id === 'second')!.projectedStartDate).toBe('2030-01-29')
  })

  it('refuses an end before the start', () => {
    expect(() => applyBaselineDates(chain, 'first', '2030-01-11', '2030-01-07', OPTIONS)).toThrow(
      /before start/,
    )
  })

  it('refuses an id that is not in the roadmap', () => {
    expect(() => applyBaselineDates(chain, 'ghost', '2030-01-07', '2030-01-11', OPTIONS)).toThrow(
      /No item with id/,
    )
  })
})

import { describe, expect, it } from 'vitest'
import {
  activeContext,
  coveredSkills,
  currentStreakWeeks,
  dimensionCoverage,
  inProgress,
  nextMilestone,
  overdueItems,
  pendingSkills,
  phaseRange,
  skillsByDimension,
  suggestedNext,
} from './dashboard'
import type { Item, Phase, Roadmap } from './types'

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

function done(id: string, completedAt: string, overrides: Partial<Item> = {}): Item {
  return item(id, { state: 'done', completedAt, ...overrides })
}

const phases: Phase[] = [
  { number: 1, name: 'First', closingMilestoneId: 'closes-one' },
  { number: 2, name: 'Second', closingMilestoneId: 'closes-two' },
]

function roadmap(overrides: Partial<Roadmap> = {}): Roadmap {
  return {
    timeZone: 'UTC',
    phases,
    blackouts: [],
    dimensions: ['Alpha', 'Beta'],
    skillDimension: {},
    ...overrides,
  }
}

describe('currentStreakWeeks', () => {
  // 2030-02-04, 2030-01-28 and 2030-01-21 are three consecutive Mondays.
  it('counts consecutive weeks with at least one completion', () => {
    const items = [
      done('a', '2030-02-06T10:00:00Z'),
      done('b', '2030-01-30T10:00:00Z'),
      done('c', '2030-01-22T10:00:00Z'),
    ]

    expect(currentStreakWeeks(items, '2030-02-07', 'UTC')).toBe(3)
  })

  it('does not break on a week that has not finished yet', () => {
    const items = [done('a', '2030-01-30T10:00:00Z'), done('b', '2030-01-22T10:00:00Z')]

    // Today is in the week of 2030-02-04, which has no completion yet.
    expect(currentStreakWeeks(items, '2030-02-05', 'UTC')).toBe(2)
  })

  it('stops at the first week with nothing completed', () => {
    const items = [done('a', '2030-02-06T10:00:00Z'), done('old', '2030-01-16T10:00:00Z')]

    expect(currentStreakWeeks(items, '2030-02-07', 'UTC')).toBe(1)
  })

  it('is zero when nothing was ever completed', () => {
    expect(currentStreakWeeks([item('a')], '2030-02-07', 'UTC')).toBe(0)
  })

  it('counts two completions in the same week once', () => {
    const items = [done('a', '2030-02-05T10:00:00Z'), done('b', '2030-02-06T10:00:00Z')]

    expect(currentStreakWeeks(items, '2030-02-07', 'UTC')).toBe(1)
  })

  it('reads the completion instant in the roadmap timezone', () => {
    // 2030-02-04T02:00Z is Monday in UTC but still Sunday 2030-02-03 in Lima,
    // which belongs to the week before. Today is the week of 2030-02-11, so in
    // UTC the streak reaches back one week and in Lima it finds a gap.
    const items = [done('a', '2030-02-04T02:00:00Z')]

    expect(currentStreakWeeks(items, '2030-02-12', 'UTC')).toBe(1)
    expect(currentStreakWeeks(items, '2030-02-12', 'America/Lima')).toBe(0)
  })
})

describe('overdueItems', () => {
  it('lists what is past due and not done, soonest first', () => {
    const items = [
      item('late-later', { projectedEndDate: '2030-02-03' }),
      item('late-first', { projectedEndDate: '2030-02-01' }),
      item('on-time', { projectedEndDate: '2030-02-20' }),
      done('late-but-done', '2030-02-02T10:00:00Z', { projectedEndDate: '2030-02-02' }),
    ]

    expect(overdueItems(items, '2030-02-05').map((entry) => entry.id)).toEqual([
      'late-first',
      'late-later',
    ])
  })
})

describe('nextMilestone', () => {
  it('picks the nearest open closing milestone', () => {
    const items = [
      item('closes-two', { projectedEndDate: '2030-06-01' }),
      item('closes-one', { projectedEndDate: '2030-03-01' }),
      item('not-a-milestone', { projectedEndDate: '2030-01-01' }),
    ]

    expect(nextMilestone(items, phases, '2030-02-01')?.item.id).toBe('closes-one')
  })

  it('skips a milestone already done', () => {
    const items = [
      done('closes-one', '2030-02-01T10:00:00Z', { projectedEndDate: '2030-03-01' }),
      item('closes-two', { projectedEndDate: '2030-06-01' }),
    ]

    expect(nextMilestone(items, phases, '2030-02-01')?.item.id).toBe('closes-two')
  })

  it('reports the days away and the pace against the baseline', () => {
    const items = [
      item('closes-one', { projectedEndDate: '2030-03-01', baselineEndDate: '2030-02-22' }),
    ]

    const status = nextMilestone(items, phases, '2030-02-01')

    expect(status?.daysAway).toBe(28)
    expect(status?.paceDays).toBe(7)
  })

  it('reports a negative pace when the projection is ahead of plan', () => {
    const items = [
      item('closes-one', { projectedEndDate: '2030-02-22', baselineEndDate: '2030-03-01' }),
    ]

    expect(nextMilestone(items, phases, '2030-02-01')?.paceDays).toBe(-7)
  })

  it('finds a milestone that is not a certification', () => {
    const items = [item('closes-one', { type: 'Project', projectedEndDate: '2030-03-01' })]

    expect(nextMilestone(items, phases, '2030-02-01')?.item.id).toBe('closes-one')
  })

  it('is null when every milestone is done', () => {
    const items = [
      done('closes-one', '2030-02-01T10:00:00Z'),
      done('closes-two', '2030-02-01T10:00:00Z'),
    ]

    expect(nextMilestone(items, phases, '2030-02-01')).toBeNull()
  })
})

describe('activeContext', () => {
  const items = [
    item('a', { phase: 1, projectedStartDate: '2030-02-01', projectedEndDate: '2030-02-28' }),
    item('b', { phase: 2, projectedStartDate: '2030-03-01', projectedEndDate: '2030-03-31' }),
  ]

  it('names the phase today falls in', () => {
    const context = activeContext('2030-03-10', roadmap(), items)

    expect(context).toEqual({ kind: 'phase', phase: phases[1] })
  })

  it('reports the non-study period instead of the phase', () => {
    const blackouts = [{ from: '2030-03-05', to: '2030-03-15', reason: 'A pause' }]

    const context = activeContext('2030-03-10', roadmap({ blackouts }), items)

    expect(context).toEqual({ kind: 'blackout', blackout: blackouts[0] })
  })

  it('says outside when today is past the whole roadmap', () => {
    expect(activeContext('2031-01-01', roadmap(), items)).toEqual({ kind: 'outside' })
  })
})

describe('phaseRange', () => {
  it('spans from the earliest start to the latest end of its items', () => {
    const items = [
      item('a', { projectedStartDate: '2030-02-10', projectedEndDate: '2030-02-20' }),
      item('b', { projectedStartDate: '2030-02-01', projectedEndDate: '2030-02-05' }),
      item('other-phase', { phase: 2, projectedStartDate: '2029-01-01' }),
    ]

    expect(phaseRange(items, phases[0]!)).toEqual({ start: '2030-02-01', end: '2030-02-20' })
  })

  it('is null for a phase with no items', () => {
    expect(phaseRange([], phases[0]!)).toBeNull()
  })
})

describe('inProgress and suggestedNext', () => {
  it('sorts what is in progress by how soon it is due', () => {
    const items = [
      item('later', { state: 'in_progress', projectedEndDate: '2030-03-01' }),
      item('sooner', { state: 'in_progress', projectedEndDate: '2030-02-10' }),
      item('pending', {}),
    ]

    expect(inProgress(items).map((entry) => entry.id)).toEqual(['sooner', 'later'])
  })

  it('suggests the pending items starting soonest', () => {
    const items = [
      item('third', { projectedStartDate: '2030-03-01' }),
      item('first', { projectedStartDate: '2030-01-01' }),
      item('second', { projectedStartDate: '2030-02-01' }),
      item('fourth', { projectedStartDate: '2030-04-01' }),
      item('running', { state: 'in_progress', projectedStartDate: '2029-01-01' }),
    ]

    expect(suggestedNext(items).map((entry) => entry.id)).toEqual(['first', 'second', 'third'])
  })
})

describe('skills', () => {
  const items = [
    done('a', '2030-02-01T10:00:00Z', { skills: ['Docker', 'MLflow'] }),
    item('b', { state: 'in_progress', skills: ['Docker', 'Triton'] }),
    item('c', { skills: ['Kubernetes'] }),
  ]

  it('covers the skills of done items', () => {
    expect(coveredSkills(items)).toEqual(['Docker', 'MLflow'])
  })

  it('leaves a skill out of pending once any done item covers it', () => {
    expect(pendingSkills(items)).toEqual(['Kubernetes', 'Triton'])
  })
})

describe('dimensionCoverage', () => {
  const world = roadmap({
    skillDimension: { Docker: 'Alpha', Kubernetes: 'Alpha', MLflow: 'Beta', Triton: 'Beta' },
  })

  it('is covered over total per dimension', () => {
    const items = [
      done('a', '2030-02-01T10:00:00Z', { skills: ['Docker'] }),
      item('b', { skills: ['Kubernetes', 'MLflow'] }),
    ]

    expect(dimensionCoverage(items, world)).toEqual([
      { dimension: 'Alpha', covered: 1, total: 2, ratio: 0.5 },
      { dimension: 'Beta', covered: 0, total: 2, ratio: 0 },
    ])
  })

  it('returns every axis even when a dimension has no skills mapped', () => {
    const coverage = dimensionCoverage([], roadmap({ skillDimension: { Docker: 'Alpha' } }))

    expect(coverage.map((entry) => entry.dimension)).toEqual(['Alpha', 'Beta'])
    expect(coverage[1]).toEqual({ dimension: 'Beta', covered: 0, total: 0, ratio: 0 })
  })

  it('ignores a skill mapped to a dimension that is not an axis', () => {
    const coverage = dimensionCoverage(
      [done('a', '2030-02-01T10:00:00Z', { skills: ['Ghost'] })],
      roadmap({ skillDimension: { Ghost: 'Unlisted' } }),
    )

    expect(coverage.every((entry) => entry.total === 0)).toBe(true)
  })
})

describe('skillsByDimension', () => {
  const world = roadmap({
    skillDimension: { Docker: 'Alpha', Kubernetes: 'Alpha', MLflow: 'Beta', Triton: 'Beta' },
  })

  it('puts covered skills first inside each axis', () => {
    const items = [
      done('a', '2030-02-01T10:00:00Z', { skills: ['Kubernetes'] }),
      item('b', { skills: ['Docker'] }),
    ]

    expect(skillsByDimension(items, world)[0]).toEqual({
      dimension: 'Alpha',
      covered: 1,
      total: 2,
      ratio: 0.5,
      skills: [
        { name: 'Kubernetes', covered: true },
        { name: 'Docker', covered: false },
      ],
    })
  })

  it('returns an axis with no skills rather than dropping it', () => {
    const only = roadmap({ skillDimension: { Docker: 'Alpha' } })

    expect(skillsByDimension([], only)[1]).toEqual({
      dimension: 'Beta',
      covered: 0,
      total: 0,
      ratio: 0,
      skills: [],
    })
  })

  it('agrees with the radar it feeds', () => {
    const items = [done('a', '2030-02-01T10:00:00Z', { skills: ['Docker'] })]

    expect(dimensionCoverage(items, world).map((entry) => entry.ratio)).toEqual(
      skillsByDimension(items, world).map((entry) => entry.ratio),
    )
  })
})

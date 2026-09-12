import { describe, expect, it } from 'vitest'
import type { Item } from '../core/types'
import { changedItems, toItem, toMeta, toPhase, toSkillDimension, type ItemRow } from './rows'

function row(overrides: Partial<ItemRow> = {}): ItemRow {
  return {
    id: 'read-the-thing',
    name: 'Read the thing',
    type: 'Book',
    phase: 1,
    skills: '["Something measurable"]',
    depends_on: '[]',
    baseline_start: '2030-01-01',
    baseline_end: '2030-01-07',
    projected_start: '2030-01-01',
    projected_end: '2030-01-07',
    price: '',
    link: null,
    notes: '',
    state: 'pending',
    completed_at: null,
    sort_order: 1,
    ...overrides,
  }
}

describe('toItem', () => {
  it('maps snake_case columns onto the domain shape', () => {
    const item = toItem(row({ depends_on: '["a","b"]', sort_order: 4 }))
    expect(item.dependsOn).toEqual(['a', 'b'])
    expect(item.baselineStartDate).toBe('2030-01-01')
    expect(item.projectedEndDate).toBe('2030-01-07')
    expect(item.sortOrder).toBe(4)
  })

  it('normalises an empty link to null', () => {
    expect(toItem(row({ link: '' })).link).toBeNull()
    expect(toItem(row({ link: 'https://example.com' })).link).toBe('https://example.com')
  })

  it('refuses a type, state or phase the schema should never have allowed', () => {
    expect(() => toItem(row({ type: 'Podcast' }))).toThrow(/unknown type/)
    expect(() => toItem(row({ state: 'started' }))).toThrow(/unknown state/)
    expect(() => toItem(row({ phase: 9 }))).toThrow(/out-of-range phase/)
  })

  it('refuses JSON columns that are not arrays of strings', () => {
    expect(() => toItem(row({ skills: 'not json' }))).toThrow(/valid JSON/)
    expect(() => toItem(row({ skills: '{"a":1}' }))).toThrow(/array of strings/)
    expect(() => toItem(row({ depends_on: '[1,2]' }))).toThrow(/array of strings/)
  })
})

describe('toPhase', () => {
  it('keeps a null closing milestone null', () => {
    const phase = toPhase({ number: 2, name: 'Second', closing_milestone_id: null })
    expect(phase.closingMilestoneId).toBeNull()
  })

  it('refuses a phase number outside 1-6', () => {
    expect(() => toPhase({ number: 0, name: 'Zero', closing_milestone_id: null })).toThrow()
  })
})

describe('row collections', () => {
  it('turns skill rows into a skill-to-axis map', () => {
    expect(
      toSkillDimension([
        { name: 'Docker', dimension: 'Infra' },
        { name: 'LoRA', dimension: 'LLM' },
      ]),
    ).toEqual({ Docker: 'Infra', LoRA: 'LLM' })
  })

  it('turns meta rows into a settings map', () => {
    expect(toMeta([{ key: 'revision', value: '7' }])).toEqual({ revision: '7' })
  })
})

describe('changedItems', () => {
  const base: Item = toItem(row())

  it('writes nothing back when nothing moved', () => {
    expect(changedItems([base], [{ ...base }])).toEqual([])
  })

  it('catches a state change, a completion and a moved projection', () => {
    expect(changedItems([base], [{ ...base, state: 'in_progress' }])).toHaveLength(1)
    expect(changedItems([base], [{ ...base, completedAt: '2030-01-05T12:00:00Z' }])).toHaveLength(1)
    expect(changedItems([base], [{ ...base, projectedEndDate: '2030-01-09' }])).toHaveLength(1)
  })

  it('ignores fields the engine never writes', () => {
    // Baselines, names and notes come from the seed, not from a state change.
    expect(changedItems([base], [{ ...base, name: 'Renamed', notes: 'edited' }])).toEqual([])
  })

  it('treats an item the previous state did not have as changed', () => {
    const added: Item = { ...base, id: 'brand-new' }
    expect(changedItems([base], [base, added]).map((item) => item.id)).toEqual(['brand-new'])
  })
})

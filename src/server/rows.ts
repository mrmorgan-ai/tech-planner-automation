import { ITEM_TYPES, PHASE_NUMBERS, STATES } from '../core/constants'
import type {
  Blackout,
  Dimension,
  Item,
  ItemType,
  Phase,
  PhaseNumber,
  Resource,
  State,
} from '../core/types'

// Mapping between D1 rows and the domain. Pure on purpose: this is where a
// column rename or a bad cast would otherwise slip through untested.

export type ItemRow = {
  id: string
  name: string
  type: string
  phase: number
  skills: string
  depends_on: string
  baseline_start: string
  baseline_end: string
  projected_start: string
  projected_end: string
  price: string
  link: string | null
  resources: string
  duration: string
  notes: string
  state: string
  completed_at: string | null
  sort_order: number
}

export type PhaseRow = { number: number; name: string; closing_milestone_id: string | null }
export type BlackoutRow = { from_date: string; to_date: string; reason: string }
export type DimensionRow = { name: string }
export type SkillRow = { name: string; dimension: string }
export type MetaRow = { key: string; value: string }

export function toItem(row: ItemRow): Item {
  if (!ITEM_TYPES.includes(row.type as ItemType)) {
    throw new Error(`${row.id} has an unknown type in the database: ${row.type}`)
  }
  if (!STATES.includes(row.state as State)) {
    throw new Error(`${row.id} has an unknown state in the database: ${row.state}`)
  }
  if (!PHASE_NUMBERS.includes(row.phase as PhaseNumber)) {
    throw new Error(`${row.id} has an out-of-range phase in the database: ${row.phase}`)
  }

  return {
    id: row.id,
    name: row.name,
    type: row.type as ItemType,
    phase: row.phase as PhaseNumber,
    skills: parseStringArray(row.skills, `${row.id}.skills`),
    dependsOn: parseStringArray(row.depends_on, `${row.id}.depends_on`),
    baselineStartDate: row.baseline_start,
    baselineEndDate: row.baseline_end,
    projectedStartDate: row.projected_start,
    projectedEndDate: row.projected_end,
    price: row.price,
    link: row.link === null || row.link === '' ? null : row.link,
    resources: parseResources(row.resources, `${row.id}.resources`),
    duration: row.duration,
    notes: row.notes,
    state: row.state as State,
    completedAt: row.completed_at,
    sortOrder: row.sort_order,
  }
}

export function toPhase(row: PhaseRow): Phase {
  if (!PHASE_NUMBERS.includes(row.number as PhaseNumber)) {
    throw new Error(`Phase ${row.number} is out of range`)
  }
  return {
    number: row.number as PhaseNumber,
    name: row.name,
    closingMilestoneId: row.closing_milestone_id,
  }
}

export function toBlackout(row: BlackoutRow): Blackout {
  return { from: row.from_date, to: row.to_date, reason: row.reason }
}

export function toSkillDimension(rows: readonly SkillRow[]): Record<string, Dimension> {
  const map: Record<string, Dimension> = {}
  for (const row of rows) map[row.name] = row.dimension
  return map
}

export function toMeta(rows: readonly MetaRow[]): Record<string, string> {
  const map: Record<string, string> = {}
  for (const row of rows) map[row.key] = row.value
  return map
}

/**
 * The items whose stored columns actually moved. Only these are written back:
 * a state change usually touches a handful of projections, not the whole
 * roadmap.
 */
export function changedItems(before: readonly Item[], after: readonly Item[]): Item[] {
  const previous = new Map(before.map((item) => [item.id, item]))
  return after.filter((item) => {
    const old = previous.get(item.id)
    if (!old) return true
    return (
      old.state !== item.state ||
      old.completedAt !== item.completedAt ||
      old.baselineStartDate !== item.baselineStartDate ||
      old.baselineEndDate !== item.baselineEndDate ||
      old.projectedStartDate !== item.projectedStartDate ||
      old.projectedEndDate !== item.projectedEndDate
    )
  })
}

function parseResources(raw: string, at: string): Resource[] {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw === '' ? '[]' : raw)
  } catch {
    throw new Error(`${at} is not valid JSON: ${raw}`)
  }
  if (!Array.isArray(parsed)) throw new Error(`${at} must be a JSON array`)
  return parsed.map((entry) => {
    const resource = entry as { label?: unknown; url?: unknown }
    if (typeof resource.label !== 'string' || typeof resource.url !== 'string') {
      throw new Error(`${at} entries must each have a string label and url`)
    }
    return { label: resource.label, url: resource.url }
  })
}

function parseStringArray(raw: string, at: string): string[] {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    throw new Error(`${at} is not valid JSON: ${raw}`)
  }
  if (!Array.isArray(parsed) || parsed.some((entry) => typeof entry !== 'string')) {
    throw new Error(`${at} must be a JSON array of strings`)
  }
  return parsed as string[]
}

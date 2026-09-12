import type { ItemType, PhaseNumber, State } from './types'

// Application structure only. Everything that describes a particular roadmap —
// phase names, non-study periods, radar axes, the skill map, the timezone — is
// content: it lives in the database and never in this repository.

export const PHASE_NUMBERS: readonly PhaseNumber[] = [1, 2, 3, 4, 5, 6] as const

export const STATES: readonly State[] = ['pending', 'in_progress', 'done'] as const

export const ITEM_TYPES: readonly ItemType[] = [
  'Certification',
  'Course',
  'Book',
  'Documentation',
  'Paper',
  'Case study',
  'Project',
] as const

/** Used only when the database has no timezone configured. */
export const DEFAULT_TIME_ZONE = 'UTC'

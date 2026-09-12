/** Study hours available per week. Roadmap content: capacity is personal. */
export type WeeklyHours = {
  normal: number
  /** The last week of each month, where time is reserved for something else. */
  lastWeekOfMonth: number
}

/** A civil date, `YYYY-MM-DD`. No time, no timezone — see dates.ts. */
export type CivilDate = string

/** An ISO datetime with offset. Only `completedAt` uses one. */
export type IsoDateTime = string

export type State = 'pending' | 'in_progress' | 'done'

export type ItemType =
  | 'Certification'
  | 'Course'
  | 'Book'
  | 'Documentation'
  | 'Paper'
  | 'Case study'
  | 'Project'

export type PhaseNumber = 1 | 2 | 3 | 4 | 5 | 6

/**
 * A radar axis. Deliberately a plain string: the axes are roadmap content and
 * live in the database, not in this repository.
 */
export type Dimension = string

/** An extra link an item carries, beyond its own `link`. */
export type Resource = {
  label: string
  url: string
}

export type Item = {
  id: string
  name: string
  type: ItemType
  phase: PhaseNumber
  skills: string[]

  /** The original plan. Never recalculated. */
  baselineStartDate: CivilDate
  baselineEndDate: CivilDate

  /** The live projection. Written only by the recalculation engine. */
  projectedStartDate: CivilDate
  projectedEndDate: CivilDate

  /** Ids scheduled before this one. A date relationship, never a lock. */
  dependsOn: string[]

  price: string
  link: string | null
  resources: Resource[]
  /**
   * How long it takes, as written: "~25h, 7 videos". The text is what is stored;
   * `estimatedHours` in hours.ts reads a number out of it when there is one.
   */
  duration: string
  /** A plain description of what the item is. No durations, no links. */
  notes: string

  state: State
  completedAt: IsoDateTime | null

  /** Curated order within a phase, for the backlog. */
  sortOrder: number
}

export type Phase = {
  number: PhaseNumber
  name: string
  /**
   * The item that closes the phase. Not derivable from `type`: a phase with no
   * certification closes on a deliverable instead.
   */
  closingMilestoneId: string | null
}

export type Blackout = {
  from: CivilDate
  to: CivilDate
  reason: string
}

/**
 * Everything about a roadmap that is content rather than application: the phase
 * names, the non-study periods, the radar axes and which axis each skill feeds.
 * Loaded from the database, never hardcoded here.
 */
export type Roadmap = {
  timeZone: string
  /**
   * The day the plan starts. Baseline dates are editable, so this is the floor
   * an edit may not go below — a mistyped year would otherwise reschedule the
   * past in silence. Empty means no floor is configured.
   */
  startDate: CivilDate | ''
  /** Study capacity per week, used to size the board's weekly scope. */
  weeklyHours: WeeklyHours
  phases: Phase[]
  blackouts: Blackout[]
  dimensions: Dimension[]
  skillDimension: Record<string, Dimension>
}

/** What the engine needs to reason about dates. */
export type ScheduleOptions = {
  blackouts: readonly Blackout[]
  timeZone: string
}

/** What every API response carries: the world, plus the server's idea of today. */
export type AppState = {
  today: CivilDate
  /** Bumped on every write. Lets a second tab notice it is looking at stale data. */
  revision: number
  /** Which seed the database was loaded from — the answer to "is this the roadmap I just edited?". */
  seedVersion: string
  roadmap: Roadmap
  items: Item[]
}

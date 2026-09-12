import { DEFAULT_TIME_ZONE } from '../core/constants'
import { recomputeProjections } from '../core/schedule'
import type { AppState, Item, Roadmap, ScheduleOptions } from '../core/types'
import { todayIn } from './clock'
import {
  changedItems,
  toBlackout,
  toItem,
  toMeta,
  toPhase,
  toSkillDimension,
  type BlackoutRow,
  type DimensionRow,
  type ItemRow,
  type MetaRow,
  type PhaseRow,
  type SkillRow,
} from './rows'

export type Env = {
  DB: D1Database
}

const ITEM_COLUMNS = `id, name, type, phase, skills, depends_on,
  baseline_start, baseline_end, projected_start, projected_end,
  price, link, resources, duration, notes, state, completed_at, sort_order`

/**
 * Reads the whole world in one batch. The roadmap is small enough that paging or
 * caching would cost more complexity than it saves, and the engine needs the
 * full dependency graph on every call anyway.
 */
export async function loadAppState(db: D1Database): Promise<AppState> {
  const [items, phases, blackouts, dimensions, skills, meta] = await db.batch([
    db.prepare(`SELECT ${ITEM_COLUMNS} FROM items ORDER BY phase, sort_order`),
    db.prepare('SELECT number, name, closing_milestone_id FROM phases ORDER BY number'),
    db.prepare('SELECT from_date, to_date, reason FROM blackouts ORDER BY from_date'),
    db.prepare('SELECT name FROM dimensions ORDER BY sort_order'),
    db.prepare('SELECT name, dimension FROM skills ORDER BY name'),
    db.prepare('SELECT key, value FROM meta'),
  ])

  const settings = toMeta((meta?.results ?? []) as MetaRow[])
  const roadmap: Roadmap = {
    timeZone: settings.time_zone ?? DEFAULT_TIME_ZONE,
    startDate: settings.start_date ?? '',
    weeklyHours: {
      // Zero reads as "not declared" downstream, which is the honest default:
      // the app never invents a capacity on the owner's behalf.
      normal: Number(settings.weekly_hours_normal ?? '0'),
      lastWeekOfMonth: Number(settings.weekly_hours_last_week ?? '0'),
    },
    phases: ((phases?.results ?? []) as PhaseRow[]).map(toPhase),
    blackouts: ((blackouts?.results ?? []) as BlackoutRow[]).map(toBlackout),
    dimensions: ((dimensions?.results ?? []) as DimensionRow[]).map((row) => row.name),
    skillDimension: toSkillDimension((skills?.results ?? []) as SkillRow[]),
  }

  return {
    today: todayIn(roadmap.timeZone),
    revision: Number(settings.revision ?? '0'),
    seedVersion: settings.seed_version ?? '0',
    roadmap,
    items: ((items?.results ?? []) as ItemRow[]).map(toItem),
  }
}

export function scheduleOptions(roadmap: Roadmap): ScheduleOptions {
  return { blackouts: roadmap.blackouts, timeZone: roadmap.timeZone }
}

/**
 * Loads, transforms, writes back only what moved, and returns the new world
 * without reading the database again. D1 has no interactive transactions, so the
 * writes go out as one batch — which it runs as a single implicit transaction.
 *
 * Two browser tabs racing is last-write-wins by design: a full recompute always
 * lands a consistent world, and the loser self-heals on its next read. That is
 * what `revision` is there to make visible.
 */
export async function mutate(
  db: D1Database,
  transform: (state: AppState) => Item[],
): Promise<AppState> {
  const state = await loadAppState(db)
  const items = transform(state)
  const changed = changedItems(state.items, items)
  const revision = state.revision + 1

  const writes = changed.map((item) =>
    db
      .prepare(
        `UPDATE items
         SET state = ?, completed_at = ?,
             baseline_start = ?, baseline_end = ?,
             projected_start = ?, projected_end = ?
         WHERE id = ?`,
      )
      .bind(
        item.state,
        item.completedAt,
        item.baselineStartDate,
        item.baselineEndDate,
        item.projectedStartDate,
        item.projectedEndDate,
        item.id,
      ),
  )
  writes.push(
    db.prepare("UPDATE meta SET value = ? WHERE key = 'revision'").bind(String(revision)),
  )

  await db.batch(writes)

  return { ...state, revision, items }
}

/** Recomputes every projection from the current baselines and completions. */
export function reproject(state: AppState): Item[] {
  return recomputeProjections(state.items, scheduleOptions(state.roadmap))
}

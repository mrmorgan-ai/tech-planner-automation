import { isCivilDate } from '../../../../src/core/dates'
import { applyBaselineDates } from '../../../../src/core/schedule'
import { only } from '../../../../src/server/http'
import { mutate, scheduleOptions, type Env } from '../../../../src/server/repository'

/**
 * Moves one item's baseline dates. The projection of everything downstream is
 * recomputed in the same write, so the plan stays continuous.
 *
 * The roadmap's start date is enforced here rather than in the engine: a floor
 * inside the engine would quietly clamp bad data instead of reporting it, and
 * the validator's strongest rule — nothing done means projected equals baseline
 * — depends on the engine not adjusting what it is given.
 */
export const onRequest = only<Env>('PATCH', async ({ env, params, request }) => {
  const id = Array.isArray(params.id) ? params.id[0] : params.id
  if (!id) return Response.json({ error: 'Missing item id' }, { status: 400 })

  let body: unknown
  try {
    body = await request.json()
  } catch {
    return Response.json({ error: 'Body must be JSON' }, { status: 400 })
  }

  const { baselineStartDate: start, baselineEndDate: end } = (body ?? {}) as {
    baselineStartDate?: unknown
    baselineEndDate?: unknown
  }

  if (typeof start !== 'string' || !isCivilDate(start)) {
    return Response.json({ error: 'baselineStartDate must be YYYY-MM-DD' }, { status: 400 })
  }
  if (typeof end !== 'string' || !isCivilDate(end)) {
    return Response.json({ error: 'baselineEndDate must be YYYY-MM-DD' }, { status: 400 })
  }
  if (end < start) {
    return Response.json({ error: `End ${end} is before start ${start}` }, { status: 400 })
  }

  try {
    const state = await mutate(env.DB, (current) => {
      const floor = current.roadmap.startDate
      if (floor !== '' && start < floor) {
        throw new Error(`The plan starts on ${floor}; ${start} is before it`)
      }
      return applyBaselineDates(current.items, id, start, end, scheduleOptions(current.roadmap))
    })
    return Response.json(state)
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    const status = message.startsWith('No item with id')
      ? 404
      : message.includes('The plan starts on')
        ? 400
        : 500
    return Response.json({ error: message }, { status })
  }
})

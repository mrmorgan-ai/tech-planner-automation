import { STATES } from '../../../../src/core/constants'
import { applyStateChange } from '../../../../src/core/schedule'
import type { State } from '../../../../src/core/types'
import { nowIso } from '../../../../src/server/clock'
import { only } from '../../../../src/server/http'
import { mutate, scheduleOptions, type Env } from '../../../../src/server/repository'

/**
 * Moves one item to a new state. Nothing here blocks anything: dependencies feed
 * the date recalculation, they never gate what you are allowed to complete.
 *
 * Returns the whole new world rather than a patch — the client replaces its
 * state wholesale, which removes a class of consistency bugs between the
 * backlog, the board and the Gantt.
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

  const next = (body as { state?: unknown } | null)?.state
  if (typeof next !== 'string' || !STATES.includes(next as State)) {
    return Response.json({ error: `state must be one of: ${STATES.join(', ')}` }, { status: 400 })
  }

  const completedAt = nowIso()

  try {
    const state = await mutate(env.DB, (current) =>
      applyStateChange(
        current.items,
        id,
        next as State,
        completedAt,
        scheduleOptions(current.roadmap),
      ),
    )
    return Response.json(state)
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    const status = message.startsWith('No item with id') ? 404 : 500
    return Response.json({ error: message }, { status })
  }
})

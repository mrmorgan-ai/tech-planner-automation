import { DEFAULT_TIME_ZONE } from '../../src/core/constants'
import { todayIn } from '../../src/server/clock'

type Env = {
  DB: D1Database
}

/**
 * Proves the whole chain end to end: the Workers runtime runs, the D1 binding
 * resolves, the schema exists and the configured timezone is readable. Kept
 * after the scaffold as the smoke test a deploy is verified with.
 */
export const onRequestGet: PagesFunction<Env> = async ({ env }) => {
  const results = await env.DB.batch([
    env.DB.prepare(
      'SELECT (SELECT COUNT(*) FROM items) AS items, (SELECT COUNT(*) FROM phases) AS phases',
    ),
    env.DB.prepare("SELECT value FROM meta WHERE key = 'time_zone'"),
  ])

  const totals = results[0]?.results?.[0] as { items: number; phases: number } | undefined
  const configured = results[1]?.results?.[0] as { value: string } | undefined
  const zone = configured?.value ?? DEFAULT_TIME_ZONE

  return Response.json({
    ok: true,
    today: todayIn(zone),
    items: totals?.items ?? 0,
    phases: totals?.phases ?? 0,
  })
}

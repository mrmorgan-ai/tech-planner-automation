import { only } from '../../src/server/http'
import { mutate, reproject, type Env } from '../../src/server/repository'

/**
 * Recomputes every projection from the current baselines. Run after reloading
 * the seed: the upsert updates baselines and dependencies but deliberately never
 * touches the projected dates, so this is what brings them back in line.
 */
export const onRequest = only<Env>('POST', async ({ env }) => {
  try {
    return Response.json(await mutate(env.DB, reproject))
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    return Response.json({ error: message }, { status: 500 })
  }
})

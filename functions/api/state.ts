import { only } from '../../src/server/http'
import { loadAppState, type Env } from '../../src/server/repository'

/** The whole world: today in the roadmap's timezone, the roadmap, every item. */
export const onRequest = only<Env>('GET', async ({ env }) => {
  return Response.json(await loadAppState(env.DB))
})

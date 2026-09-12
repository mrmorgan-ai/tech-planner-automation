import type { AppState, CivilDate, State } from '../core/types'

/**
 * Every call answers with the whole world, so the client replaces its state
 * instead of merging a patch. The API reports the error message itself; falling
 * back to the status code only matters when the response is not JSON at all.
 */
async function call(url: string, init?: RequestInit): Promise<AppState> {
  const response = await fetch(url, init)
  const body: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    const reported = (body as { error?: string } | null)?.error
    throw new Error(reported ?? `HTTP ${response.status}`)
  }
  return body as AppState
}

export function fetchState(): Promise<AppState> {
  return call('/api/state')
}

export function setItemState(id: string, state: State): Promise<AppState> {
  return call(`/api/items/${encodeURIComponent(id)}/state`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ state }),
  })
}

/** Moves an item's plan. The server recomputes every projection and returns it. */
export function setItemDates(
  id: string,
  baselineStartDate: CivilDate,
  baselineEndDate: CivilDate,
): Promise<AppState> {
  return call(`/api/items/${encodeURIComponent(id)}/dates`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ baselineStartDate, baselineEndDate }),
  })
}

import { useCallback, useEffect, useState } from 'react'
import type { AppState, State } from '../core/types'
import { fetchState, setItemState } from './api'

export type Store = {
  state: AppState | null
  error: string | null
  /** The item currently being written, so one row can show it without freezing the rest. */
  pendingId: string | null
  changeState: (id: string, next: State) => Promise<void>
}

/**
 * The single copy of the world in the browser. No optimistic update on purpose:
 * the server answers a state change with the recalculated roadmap, and guessing
 * that result locally would mean reimplementing the engine in the client.
 */
export function useAppState(): Store {
  const [state, setState] = useState<AppState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchState()
      .then((loaded) => {
        if (!cancelled) setState(loaded)
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(messageOf(cause))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const changeState = useCallback(async (id: string, next: State) => {
    setPendingId(id)
    setError(null)
    try {
      setState(await setItemState(id, next))
    } catch (cause: unknown) {
      setError(messageOf(cause))
    } finally {
      setPendingId(null)
    }
  }, [])

  return { state, error, pendingId, changeState }
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'Unknown error'
}

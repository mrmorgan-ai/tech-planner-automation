/**
 * Subscribing to a run's event stream.
 *
 * The stream is the state. The server replays every event from the beginning
 * of the run whenever a client attaches, so this hook needs no cursor, no
 * reconciliation and no polling — it can rebuild the whole transcript from a
 * fresh connection, which is what makes a page refresh mid-plan survivable.
 *
 * One detail matters more than it looks. `EventSource` reconnects on its own
 * whenever the connection closes, and a finished run closes it — so without
 * explicitly closing on `stream_closed` the browser would reconnect forever,
 * replaying the same completed run every few seconds. That terminal event
 * exists precisely so this side knows the difference between "the run ended"
 * and "the connection dropped".
 */

import { useEffect, useReducer } from 'react'
import type { CreatedItem, Proposal, Report } from './api'
import { eventsUrl } from './api'

export interface Entry {
  id: number
  kind: 'assistant' | 'tool' | 'notice' | 'status' | 'error'
  text: string
  detail?: string
  ok?: boolean
}

export interface RunState {
  entries: Entry[]
  /** The assistant turn currently arriving, token by token. */
  streaming: string
  proposal: Proposal | null
  report: Report | null
  awaiting: boolean
  created: CreatedItem[]
  failure: string | null
  mcpServers: string[]
  /** True while the stream is open and the run has not reported an end. */
  live: boolean
  connected: boolean
  /**
   * True while the agent is working on the current turn.
   *
   * Distinct from `live`, and the distinction is what makes a conversation
   * usable: an interactive session stays live from the first message until it
   * closes, so gating the composer on `live` would disable it forever after
   * the first turn. This gates it on the turn instead.
   */
  thinking: boolean
  /** Turns completed. Bumped on every `turn_ended`. */
  turns: number
}

const EMPTY: RunState = {
  entries: [],
  streaming: '',
  proposal: null,
  report: null,
  awaiting: false,
  created: [],
  failure: null,
  mcpServers: [],
  live: false,
  connected: false,
  thinking: false,
  turns: 0,
}

type Action =
  | { type: 'reset' }
  | { type: 'connected'; value: boolean }
  | { type: 'event'; name: string; data: Record<string, unknown> }

let nextId = 0

function reducer(state: RunState, action: Action): RunState {
  switch (action.type) {
    case 'reset':
      return EMPTY
    case 'connected':
      return { ...state, connected: action.value }
    case 'event':
      return apply(state, action.name, action.data)
  }
}

function entry(state: RunState, kind: Entry['kind'], text: string, extra?: Partial<Entry>) {
  return [...state.entries, { id: nextId++, kind, text, ...extra }]
}

/** Close the assistant turn that was streaming, if there is one. */
function settle(state: RunState): RunState {
  if (!state.streaming.trim()) return { ...state, streaming: '' }
  return {
    ...state,
    entries: entry(state, 'assistant', state.streaming),
    streaming: '',
  }
}

function apply(state: RunState, name: string, data: Record<string, unknown>): RunState {
  const str = (key: string) => (data[key] as string) ?? ''
  switch (name) {
    case 'run_started':
      return {
        ...state,
        live: true,
        thinking: true,
        mcpServers: (data.mcp_servers as string[]) ?? [],
        // A short greeting, not an inventory. The connector list was ten lines
        // of things the user did not ask about, in front of the one thing they
        // did. The servers are still carried on the state for anyone who wants
        // to show them somewhere quieter.
        entries: entry(state, 'status', "Ready — let's plan."),
      }
    case 'assistant_delta':
      return { ...state, streaming: state.streaming + str('text') }
    case 'assistant_message':
      // The deltas already carried the text; this only marks the turn's end.
      return settle(state)
    case 'tool_started': {
      const settled = settle(state)
      return { ...settled, entries: entry(settled, 'tool', str('name'), { detail: str('detail') }) }
    }
    case 'tool_finished': {
      if (data.ok !== false) return state
      const settled = settle(state)
      return {
        ...settled,
        entries: entry(settled, 'tool', str('name'), { detail: str('detail'), ok: false }),
      }
    }
    case 'agent_retrying': {
      const settled = settle(state)
      // Worth showing rather than swallowing: on a subscription this is the
      // difference between "backing off" and "hung".
      return { ...settled, entries: entry(settled, 'notice', `waiting — ${str('reason')}`) }
    }
    case 'notice': {
      const settled = settle(state)
      return { ...settled, entries: entry(settled, 'notice', str('message')) }
    }
    case 'proposal_ready':
      return { ...settle(state), proposal: data.proposal as Proposal }
    case 'plan_validated':
      return { ...settle(state), report: data.report as Report }
    case 'awaiting_approval':
      return { ...settle(state), awaiting: true }
    case 'approval_recorded': {
      const settled = settle(state)
      const approved = data.approved === true
      return {
        ...settled,
        awaiting: false,
        entries: entry(settled, 'status', approved ? 'approved' : 'rejected — nothing was created'),
      }
    }
    case 'creation_reported':
      return { ...settle(state), created: (data.items as CreatedItem[]) ?? [] }
    case 'run_failed': {
      const settled = settle(state)
      return {
        ...settled,
        live: false,
        thinking: false,
        awaiting: false,
        failure: str('reason'),
        entries: entry(settled, 'error', str('reason')),
      }
    }
    case 'turn_ended':
      // The agent finished answering. The session stays open — this is what
      // lets the user type the next turn without starting a new run.
      return { ...settle(state), thinking: false, turns: state.turns + 1 }
    case 'stream_closed':
      return { ...settle(state), live: false, thinking: false }
    default:
      return state
  }
}

/** Every event the server emits. Listed because `EventSource` dispatches by name. */
const EVENT_NAMES = [
  'run_started',
  'assistant_delta',
  'assistant_message',
  'tool_started',
  'tool_finished',
  'agent_retrying',
  'notice',
  'proposal_ready',
  'plan_validated',
  'awaiting_approval',
  'approval_recorded',
  'creation_reported',
  'turn_ended',
  'run_failed',
  'stream_closed',
  'unknown',
]

/**
 * Subscribe to `sessionId`'s current run.
 *
 * `runKey` counts the passes: 0 means nothing has been started, and every
 * increment re-subscribes from scratch. It has to be the number rather than a
 * boolean, because the propose pass and the create pass are two separate runs
 * on the *same* session — collapsing them to "enabled" would leave the second
 * one with no subscriber at all, so approving would appear to do nothing.
 */
export function useRun(sessionId: string | null, runKey: number): RunState {
  const [state, dispatch] = useReducer(reducer, EMPTY)

  useEffect(() => {
    dispatch({ type: 'reset' })
    if (!sessionId || runKey === 0) return

    const source = new EventSource(eventsUrl(sessionId))
    source.onopen = () => dispatch({ type: 'connected', value: true })
    source.onerror = () => dispatch({ type: 'connected', value: false })

    for (const name of EVENT_NAMES) {
      source.addEventListener(name, (message) => {
        const data = JSON.parse((message as MessageEvent).data) as Record<string, unknown>
        dispatch({ type: 'event', name, data })
        if (name === 'stream_closed') {
          // Otherwise the browser reconnects and replays the finished run.
          source.close()
          dispatch({ type: 'connected', value: false })
        }
      })
    }

    return () => source.close()
  }, [sessionId, runKey])

  return state
}

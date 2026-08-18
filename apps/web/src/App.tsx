/**
 * The three-panel app, and the only place that holds session state.
 *
 * The division of labour is worth stating, because it is what makes a refresh
 * mid-plan harmless: the **stream** carries what is happening right now, and
 * the **session record** carries what has happened. So the transcript comes
 * from the event stream, while the proposal, the findings and the created
 * items are re-read from the server whenever a run ends. Nothing important is
 * held only in a browser tab.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type Health, type Session } from './api'
import { useRun, type Entry } from './useRun'
import { Conversation } from './panels/Conversation'
import { Files } from './panels/Files'
import { PromptEditor } from './panels/PromptEditor'

const CADENCES = [
  { value: 'sprint', label: 'Sprint — stories into tasks' },
  { value: 'quarterly', label: 'Quarterly — features into stories' },
  { value: 'annual', label: 'Annual — epics into features' },
]

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [session, setSession] = useState<Session | null>(null)
  const [history, setHistory] = useState<Entry[]>([])
  // Bumped for each pass. A change re-subscribes, which is what makes the
  // create pass a new stream rather than a continuation of the propose pass.
  const [runKey, setRunKey] = useState(0)
  // Only ever true while an HTTP call is in flight. Whether a *run* is going
  // is read from the stream instead — an earlier version kept one `busy` flag
  // for both, and a run that failed before emitting anything left it stuck on
  // forever, which locked the composer with no way back.
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The prompt is edited occasionally and read rarely, so it is a dialog
  // rather than a third of the screen permanently given over to it.
  const [promptOpen, setPromptOpen] = useState(false)
  const [cadence, setCadence] = useState('sprint')
  const [sprint, setSprint] = useState('')
  const [buffer, setBuffer] = useState('')

  const run = useRun(session?.id ?? null, runKey)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  // `?session=<id>` reopens an existing session and attaches to its run. The
  // server replays a run from the beginning whenever a client subscribes, so a
  // finished pass renders in full — which is what makes a link to a session
  // worth having, and what lets a closed tab be picked back up.
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get('session')
    if (!wanted) return
    api
      .getSession(wanted)
      .then((found) => {
        setSession(found)
        setHistory([])
        setRunKey(1)
      })
      .catch((caught: Error) => setError(caught.message))
  }, [])

  // When a pass ends, re-read the record. The stream told us what happened;
  // this is what makes it durable, and it is where `created` comes from after
  // a create pass that the propose stream knew nothing about.
  useEffect(() => {
    if (!session || runKey === 0) return
    if (run.thinking || run.entries.length === 0) return
    api.getSession(session.id).then(setSession).catch(() => {})
    api.health().then(setHealth).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.turns, run.live])

  // A finished run's entries would otherwise vanish when the next pass resets
  // the stream, so they are kept once the stream itself is over.
  useEffect(() => {
    if (runKey === 0 || run.live || run.entries.length === 0) return
    setHistory((previous) => [...previous, ...run.entries])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.live])

  const start = useCallback(async () => {
    setPending(true)
    setError(null)
    try {
      const created = await api.createSession({
        cadence,
        sprint: sprint || null,
        buffer_factor: buffer || null,
      })
      setSession(created)
      setHistory([])
      setRunKey(0)
      return created
    } catch (caught) {
      setError((caught as Error).message)
      return null
    } finally {
      setPending(false)
    }
  }, [cadence, sprint, buffer])

  // Typing a requirement opens a session if there is not one yet. Making the
  // user press a separate button first only ever meant a disabled text box and
  // no explanation of what to do about it.
  const send = async (text: string) => {
    const active = session ?? (await start())
    if (!active) return
    setPending(true)
    setError(null)
    try {
      const answer = await api.sendMessage(active.id, text)
      // Only a newly opened session needs a subscription. A continued turn
      // arrives on the stream that is already attached, and resubscribing
      // would throw away the transcript so far to replay it.
      if (answer.started) setRunKey((key) => key + 1)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setPending(false)
    }
  }

  const decide = async (approved: boolean, note: string) => {
    if (!session) return
    setPending(true)
    setError(null)
    try {
      await api.approve(session.id, approved, note)
      setRunKey((key) => key + 1)
    } catch (caught) {
      // A 409 here is the gate refusing, with the rules that blocked it.
      setError((caught as Error).message)
    } finally {
      setPending(false)
    }
  }

  const cancel = async () => {
    if (!session) return
    await api.cancelRun(session.id).catch(() => {})
  }

  // `run.live` stays true for the life of a conversation, so gating on it
  // would disable the composer after the first turn and never re-enable it.
  const busy = pending || run.thinking
  // Deduplicated by id. A finished run's entries live in both `history` and
  // `run.entries` until the next pass resets the stream, and concatenating
  // them blind renders the whole transcript twice in that window.
  const entries = useMemo(() => {
    const byId = new Map<number, Entry>()
    for (const item of [...history, ...run.entries]) byId.set(item.id, item)
    return [...byId.values()]
  }, [history, run.entries])
  const proposal = run.proposal ?? session?.proposal ?? null
  const report = run.report ?? session?.report ?? null
  const created = run.created.length > 0 ? run.created : (session?.created ?? [])
  const awaiting = run.awaiting || session?.status === 'proposed'

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <strong>Planify</strong>
          <span className="tagline">running on your Claude Code subscription</span>
        </div>

        <div className="controls">
          <select value={cadence} onChange={(event) => setCadence(event.target.value)}>
            {CADENCES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <input
            className="narrow"
            value={sprint}
            placeholder="sprint"
            onChange={(event) => setSprint(event.target.value)}
          />
          <input
            className="narrow"
            value={buffer}
            placeholder={`×${health ? '1.30' : ''}`}
            onChange={(event) => setBuffer(event.target.value)}
          />
          <button onClick={() => setPromptOpen(true)}>Prompt</button>
          <button onClick={() => void start()} disabled={busy}>
            New session
          </button>
        </div>

        <div className={`health ${health?.ok ? 'ok' : 'bad'}`} title={health?.config ?? ''}>
          {health ? (
            <>
              {health.backend} · {health.profile}
              {health.active_runs.length > 0 && ` · ${health.active_runs.length} running`}
            </>
          ) : (
            'API unreachable — is `make api` running?'
          )}
        </div>
      </header>

      {error && (
        <div className="banner" onClick={() => setError(null)}>
          {error} <span className="dismiss">dismiss</span>
        </div>
      )}

      <main className="panels">
        <Conversation
          session={session}
          entries={entries}
          streaming={run.streaming}
          live={run.live}
          proposal={proposal}
          report={report}
          awaiting={Boolean(awaiting && proposal)}
          created={created}
          busy={busy}
          onSend={send}
          onDecide={decide}
          onCancel={cancel}
        />
        <Files onError={setError} />
      </main>

      {promptOpen && <PromptEditor onError={setError} onClose={() => setPromptOpen(false)} />}
    </div>
  )
}

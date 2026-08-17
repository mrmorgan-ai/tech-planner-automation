/**
 * The transcript panel: what the agent is doing, what it proposed, and the gate.
 */

import { useEffect, useRef, useState } from 'react'
import type { CreatedItem, Proposal, Report, Session } from '../api'
import type { Entry } from '../useRun'
import { ApprovalCard } from '../components/ApprovalCard'
import { PlanTree } from '../components/PlanTree'

export interface ConversationProps {
  session: Session | null
  entries: Entry[]
  streaming: string
  live: boolean
  proposal: Proposal | null
  report: Report | null
  awaiting: boolean
  created: CreatedItem[]
  busy: boolean
  onSend: (text: string) => void
  onDecide: (approved: boolean, note: string) => void
  onCancel: () => void
}

export function Conversation(props: ConversationProps) {
  const { session, entries, streaming, live, proposal, report, awaiting, created } = props
  const [text, setText] = useState('')
  const tail = useRef<HTMLDivElement>(null)

  useEffect(() => {
    tail.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [entries.length, streaming, proposal, created.length])

  const send = () => {
    if (!text.trim() || props.busy) return
    props.onSend(text.trim())
    setText('')
  }

  return (
    <section className="panel conversation">
      <header className="panel-head">
        <h2>Conversation</h2>
        {session && (
          <div className="session-meta">
            <span className={`status status-${session.status}`}>{session.status}</span>
            <span>{session.scope}</span>
            <span>×{session.buffer_factor}</span>
            {session.plans_tasks && session.capacity_hours && (
              <span>{session.capacity_hours}h capacity</span>
            )}
            {live && (
              <button className="link" onClick={props.onCancel}>
                stop
              </button>
            )}
          </div>
        )}
      </header>

      <div className="transcript">
        {!session && (
          <div className="empty">
            <p>
              Describe a requirement below and press Plan it. A session opens on the first
              message — it runs on your own Claude Code subscription, with your MCP servers,
              plugins and skills available to it.
            </p>
            <p className="hint">
              Nothing is written to the backend until you approve it. During planning the
              tools that create work items are denied outright, not merely discouraged.
            </p>
          </div>
        )}

        {entries.map((entry) => (
          <EntryLine key={entry.id} entry={entry} />
        ))}
        {streaming && <div className="entry assistant">{streaming}</div>}
        {live && !streaming && (
          // A planning turn goes quiet for a minute at a time while the agent
          // reads and thinks. Without something moving, a working run and a
          // hung one look identical.
          <div className="thinking">
            <span className="dot" />
            <span className="dot" />
            <span className="dot" />
          </div>
        )}

        {proposal && (
          <>
            <h3 className="section">Proposed plan</h3>
            <PlanTree proposal={proposal} />
          </>
        )}

        {proposal && awaiting && (
          <ApprovalCard
            proposal={proposal}
            report={report}
            busy={props.busy}
            onDecide={props.onDecide}
          />
        )}

        {created.length > 0 && (
          <div className="created">
            <h3 className="section">Created {created.length} work items</h3>
            {created.map((item) => (
              <div className="created-row" key={item.ref}>
                <code>{item.ref}</code>
                {item.url ? (
                  <a href={item.url} target="_blank" rel="noreferrer">
                    {item.backend_id}
                  </a>
                ) : (
                  <span>{item.backend_id}</span>
                )}
              </div>
            ))}
          </div>
        )}

        <div ref={tail} />
      </div>

      <div className="composer">
        <textarea
          rows={3}
          value={text}
          // Never disabled for want of a session — sending opens one. Only a
          // run already in flight closes the box, and the stop button next to
          // the status is always there to reopen it.
          disabled={props.busy}
          placeholder="Describe the requirement to plan…"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends; Shift+Enter is a newline. Requirements are usually
            // one line, and the ones that are not are pasted.
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              send()
            }
          }}
        />
        <button className="primary" disabled={props.busy || !text.trim()} onClick={send}>
          {props.busy ? 'Working…' : 'Plan it'}
        </button>
      </div>
    </section>
  )
}

function EntryLine({ entry }: { entry: Entry }) {
  if (entry.kind === 'tool') {
    return (
      <div className={`entry tool${entry.ok === false ? ' failed' : ''}`}>
        <span className="arrow">{entry.ok === false ? '←' : '→'}</span>
        <code>{entry.text}</code>
        {entry.detail && <span className="detail">{entry.detail}</span>}
      </div>
    )
  }
  if (entry.kind === 'assistant') return <div className="entry assistant">{entry.text}</div>
  return (
    <div className={`entry ${entry.kind}`}>
      {entry.text}
      {entry.detail && <span className="detail"> · {entry.detail}</span>}
    </div>
  )
}

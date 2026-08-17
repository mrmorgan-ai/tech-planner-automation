/**
 * The gate, as the user sees it.
 *
 * It lists exactly what would be written and every finding the rules raised,
 * because that is the whole argument for proposing before creating. Errors
 * disable the approve button — but the button is a courtesy, not the gate: the
 * session aggregate refuses the same approval on the server, and the backend's
 * write tools stay denied until it has accepted one. Nothing here can be
 * clicked into creating work items.
 */

import { useState } from 'react'
import type { Proposal, Report } from '../api'

export function ApprovalCard({
  proposal,
  report,
  busy,
  onDecide,
}: {
  proposal: Proposal
  report: Report | null
  busy: boolean
  onDecide: (approved: boolean, note: string) => void
}) {
  const [note, setNote] = useState('')
  const errors = report?.violations.filter((v) => v.severity === 'error') ?? []
  const others = report?.violations.filter((v) => v.severity !== 'error') ?? []
  const blocked = errors.length > 0

  return (
    <div className={`approval${blocked ? ' blocked' : ''}`}>
      <div className="approval-head">
        <strong>{proposal.items.length} work items</strong> will be created in the backend.
      </div>

      {report && report.violations.length === 0 && (
        <p className="finding ok">✓ this plan breaks none of the planning rules</p>
      )}
      {errors.map((violation, index) => (
        <p className="finding error" key={`e${index}`}>
          <span className="mark">✗</span>
          {violation.item_ref && <code>{violation.item_ref}</code>} {violation.message}
        </p>
      ))}
      {others.map((violation, index) => (
        <p className={`finding ${violation.severity}`} key={`w${index}`}>
          <span className="mark">{violation.severity === 'warning' ? '!' : '·'}</span>
          {violation.item_ref && <code>{violation.item_ref}</code>} {violation.message}
        </p>
      ))}

      {blocked && (
        <p className="approval-blocked">
          This plan breaks a mandatory planning rule and cannot be created. Warnings are yours
          to weigh; these are not. Revise the requirement and plan again.
        </p>
      )}

      <textarea
        className="approval-note"
        placeholder={blocked ? 'Why it is being rejected…' : 'Note (optional)'}
        value={note}
        rows={2}
        onChange={(event) => setNote(event.target.value)}
      />
      <div className="approval-actions">
        <button
          className="primary"
          disabled={blocked || busy}
          onClick={() => onDecide(true, note)}
          title={blocked ? 'blocked by a mandatory rule' : 'create these items'}
        >
          Approve and create
        </button>
        <button disabled={busy} onClick={() => onDecide(false, note)}>
          Reject
        </button>
      </div>
    </div>
  )
}

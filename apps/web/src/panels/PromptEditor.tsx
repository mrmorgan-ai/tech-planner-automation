/**
 * The system prompt, editable.
 *
 * A plain textarea over `prompts/system.md`, and deliberately nothing more.
 * The prompt is the whole of what the agent is told — no CLAUDE.md is injected
 * from anywhere — so what is in this box is what runs. Validating or
 * "improving" it here would put the tool between the user and the only lever
 * they have.
 *
 * Only the editable half is shown. The backend adapter's field mapping is
 * appended server-side and can be read below, but is not the user's to edit:
 * it is how a backend is described, not how planning is done.
 */

import { useEffect, useState } from 'react'
import { api } from '../api'

export function PromptEditor({
  onError,
  onClose,
}: {
  onError: (message: string) => void
  onClose: () => void
}) {
  const [text, setText] = useState('')
  const [saved, setSaved] = useState('')
  const [assembled, setAssembled] = useState('')
  const [placeholders, setPlaceholders] = useState<string[]>([])
  const [showAssembled, setShowAssembled] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = () =>
    api
      .readPrompt()
      .then((prompt) => {
        setText(prompt.text)
        setSaved(prompt.text)
        setAssembled(prompt.assembled)
        setPlaceholders(prompt.unfilled_placeholders)
      })
      .catch((error: Error) => onError(error.message))

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const dirty = text !== saved

  const save = async () => {
    setBusy(true)
    try {
      await api.writePrompt(text)
      await load()
    } catch (error) {
      onError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section
        className="panel prompt modal"
        onClick={(event) => event.stopPropagation()}
      >
      <header className="panel-head">
        <h2>System prompt</h2>
        <div className="panel-actions">
          {dirty && <span className="dirty">unsaved</span>}
          <button className="link" onClick={() => setShowAssembled((value) => !value)}>
            {showAssembled ? 'edit' : 'preview sent'}
          </button>
          <button onClick={() => setText(saved)} disabled={!dirty || busy}>
            Revert
          </button>
          <button className="primary" onClick={save} disabled={!dirty || busy}>
            Save
          </button>
          <button className="link" onClick={onClose} title="close">
            ✕
          </button>
        </div>
      </header>

      {placeholders.length > 0 && (
        <p className="warn">
          Unfilled placeholders: {placeholders.join(', ')} — add them to your backend options in
          config/settings.py.
        </p>
      )}

      {showAssembled ? (
        <pre className="assembled">{assembled}</pre>
      ) : (
        <textarea
          className="prompt-text"
          value={text}
          spellCheck={false}
          onChange={(event) => setText(event.target.value)}
        />
      )}

      <footer className="panel-foot">
        {showAssembled
          ? `${assembled.length} characters sent to the agent, adapter included`
          : 'Saved changes apply to the next pass, not one already running.'}
      </footer>
      </section>
    </div>
  )
}

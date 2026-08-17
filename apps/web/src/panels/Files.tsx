/**
 * Context documents, and the numbers a sprint is planned against.
 *
 * Documents are dropped in, and land as real files on disk. That last part is
 * the point: the agent has file tools, so it is given a *path* and reads the
 * parts it needs, rather than having a standards document pushed through the
 * context window on turn one. Uploading and attaching-by-path therefore differ
 * only in how the bytes arrive; both end up as a file the agent can open.
 *
 * Capacity shares this panel because it has nowhere better to live: it is not
 * a property of the team but of *this* sprint — two people on holiday, a
 * support rotation — so it changes every couple of weeks and belongs somewhere
 * you can edit it in a second.
 */

import { useEffect, useRef, useState } from 'react'
import type { Capacity, ContextFile } from '../api'
import { api } from '../api'

export function Files({ onError }: { onError: (message: string) => void }) {
  const [files, setFiles] = useState<ContextFile[]>([])
  const [path, setPath] = useState('')
  const [capacity, setCapacity] = useState<Capacity | null>(null)
  const [dragging, setDragging] = useState(false)
  const picker = useRef<HTMLInputElement>(null)
  const [sprint, setSprint] = useState('')
  const [hours, setHours] = useState('')

  const load = async () => {
    try {
      setFiles(await api.listContext())
      setCapacity(await api.capacity())
    } catch (error) {
      onError((error as Error).message)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const upload = async (files: FileList | File[]) => {
    if (!files || Array.from(files).length === 0) return
    try {
      await api.uploadContext(files)
      await load()
    } catch (error) {
      onError((error as Error).message)
    }
  }

  const attach = async () => {
    if (!path.trim()) return
    try {
      await api.attachContext(path.trim())
      setPath('')
      await load()
    } catch (error) {
      onError((error as Error).message)
    }
  }

  const record = async () => {
    if (!sprint.trim() || !hours.trim()) return
    try {
      await api.setCapacity(sprint.trim(), hours.trim())
      setSprint('')
      setHours('')
      await load()
    } catch (error) {
      onError((error as Error).message)
    }
  }

  return (
    <section className="panel files">
      <header className="panel-head">
        <h2>Files</h2>
      </header>

      <div
        className={`dropzone${dragging ? ' over' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          void upload(event.dataTransfer.files)
        }}
        onClick={() => picker.current?.click()}
      >
        <strong>Drop files here</strong>
        <span>or click to choose</span>
        <input
          ref={picker}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            if (event.target.files) void upload(event.target.files)
            event.target.value = ''
          }}
        />
      </div>

      <details className="by-path">
        <summary>attach by path instead</summary>
        <div className="file-add">
          <input
            value={path}
            placeholder="/path/to/requirements.md"
            onChange={(event) => setPath(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && attach()}
          />
          <button onClick={attach} disabled={!path.trim()}>
            Attach
          </button>
        </div>
      </details>

      {files.length === 0 ? (
        <p className="empty small">
          Nothing attached. Requirement docs, backlogs, architecture notes and standards all
          make for better estimates than the requirement text alone.
        </p>
      ) : (
        <ul className="file-list">
          {files.map((file) => (
            <li key={file.name}>
              <span className="file-name">{file.name}</span>
              <span className="file-size">{Math.max(1, Math.round(file.size_bytes / 1024))} KB</span>
              <button
                className="link"
                onClick={async () => {
                  try {
                    await api.detachContext(file.name)
                    await load()
                  } catch (error) {
                    onError((error as Error).message)
                  }
                }}
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <header className="panel-head sub">
        <h2>Sprint capacity</h2>
      </header>
      {capacity && (
        <>
          <p className="empty small">
            Default {capacity.default_hours}h per story · buffer ×{capacity.buffer_factor}
          </p>
          {Object.entries(capacity.sprints).length > 0 && (
            <ul className="file-list">
              {Object.entries(capacity.sprints).map(([name, value]) => (
                <li key={name}>
                  <span className="file-name">{name}</span>
                  <span className="file-size">{value}h</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <div className="file-add">
        <input
          value={sprint}
          placeholder="2026Q3SP3"
          onChange={(event) => setSprint(event.target.value)}
        />
        <input
          className="narrow"
          value={hours}
          placeholder="48"
          onChange={(event) => setHours(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && record()}
        />
        <button onClick={record} disabled={!sprint.trim() || !hours.trim()}>
          Set
        </button>
      </div>
    </section>
  )
}

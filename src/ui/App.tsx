import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

type Health = { ok: boolean; today: string; items: number }

const VIEWS = [
  { path: '/dashboard', label: 'Dashboard' },
  { path: '/backlog', label: 'Backlog' },
  { path: '/kanban', label: 'Kanban' },
  { path: '/gantt', label: 'Gantt' },
] as const

function Placeholder({ view }: { view: string }) {
  return (
    <section className="placeholder">
      <h2>{view}</h2>
      <p>Not built yet.</p>
    </section>
  )
}

export function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then(setHealth)
      .catch((err: Error) => setError(err.message))
  }, [])

  return (
    <div className="app">
      <header>
        <strong>Planify</strong>
        <nav>
          {VIEWS.map((view) => (
            <NavLink key={view.path} to={view.path}>
              {view.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          {VIEWS.map((view) => (
            <Route key={view.path} path={view.path} element={<Placeholder view={view.label} />} />
          ))}
          <Route path="*" element={<Placeholder view="Not found" />} />
        </Routes>
      </main>

      <footer>
        {error && <span className="bad">api: {error}</span>}
        {health && (
          <span className="good">
            api ok · today {health.today} · {health.items} items in D1
          </span>
        )}
      </footer>
    </div>
  )
}

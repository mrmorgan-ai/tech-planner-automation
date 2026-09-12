import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { Backlog } from './Backlog'
import { Dashboard } from './Dashboard'
import { Gantt } from './Gantt'
import { Kanban } from './Kanban'
import { useAppState } from './useAppState'

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
  const store = useAppState()
  const { state, error } = store

  return (
    <div className="app">
      <header>
        <Link className="brand" to="/dashboard">
          Planify
        </Link>
        <nav>
          {VIEWS.map((view) => (
            <NavLink key={view.path} to={view.path}>
              {view.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main>
        {!state && !error && <p className="empty">Loading the roadmap…</p>}
        {state && (
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard state={state} />} />
            <Route path="/gantt" element={<Gantt state={state} />} />
            <Route path="/backlog" element={<Backlog {...store} state={state} />} />
            <Route path="/kanban" element={<Kanban {...store} state={state} />} />
            <Route path="*" element={<Placeholder view="Not found" />} />
          </Routes>
        )}
      </main>

      <footer>
        {error && <span className="bad">{error}</span>}
        {state && (
          <span className="muted">
            today {state.today} · {state.items.length} items
          </span>
        )}
      </footer>
    </div>
  )
}

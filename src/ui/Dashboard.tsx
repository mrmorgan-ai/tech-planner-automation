import { Link } from 'react-router-dom'
import {
  activeContext,
  coveredSkills,
  currentStreakWeeks,
  dimensionCoverage,
  inProgress,
  nextMilestone,
  overdueItems,
  pendingSkills,
  suggestedNext,
} from '../core/dashboard'
import { phaseProgress } from '../core/selectors'
import type { AppState, Item } from '../core/types'
import { Radar } from './Radar'

const SHOWN_IN_PROGRESS = 5

/**
 * Four blocks answering four questions: how am I doing, what am I on right now,
 * what have I covered, and what does the profile look like. The Gantt is the
 * fifth and lives in its own view, linked from here.
 *
 * Numbers and dates, no progress charts — the radar is the one exception.
 */
export function Dashboard({ state }: { state: AppState }) {
  const { items, today, roadmap } = state
  const streak = currentStreakWeeks(items, today, roadmap.timeZone)
  const late = overdueItems(items, today)
  const milestone = nextMilestone(items, roadmap.phases, today)
  const context = activeContext(today, roadmap, items)
  const running = inProgress(items)
  const covered = coveredSkills(items)
  const pending = pendingSkills(items)

  return (
    <div className="dashboard">
      <section className="block">
        <h2>Progress</h2>
        <div className="stats">
          <Stat label="Streak" value={streak === 0 ? 'none' : `${streak}w`}>
            {streak === 0 ? 'no week closed with a completion yet' : 'weeks in a row with a completion'}
          </Stat>

          <Stat label="Overdue" value={String(late.length)} bad={late.length > 0}>
            {late.length === 0 ? 'nothing past its date' : late[0]!.name}
          </Stat>

          <Stat
            label="Next milestone"
            value={milestone ? `${milestone.daysAway}d` : '—'}
            bad={milestone !== null && milestone.daysAway < 0}
          >
            {milestone ? `${milestone.item.name} · ${milestone.item.projectedEndDate}` : 'all closed'}
          </Stat>

          <Stat
            label="Pace"
            value={milestone ? signed(milestone.paceDays) : '—'}
            bad={milestone !== null && milestone.paceDays > 0}
            good={milestone !== null && milestone.paceDays < 0}
          >
            {paceReading(milestone?.paceDays)}
          </Stat>

          <Stat label="Today" value={contextValue(context)} wide>
            {context.kind === 'blackout' ? 'planned pause, not a slip' : today}
          </Stat>
        </div>

        <div className="phase-bars">
          {roadmap.phases.map((phase) => {
            const progress = phaseProgress(items, phase)
            return (
              <div key={phase.number} className="phase-row">
                <span className="phase-index">{phase.number}</span>
                <span className="phase-name">{phase.name}</span>
                <span className="phase-progress">
                  {progress.done}/{progress.total}
                </span>
              </div>
            )
          })}
        </div>
      </section>

      <section className="block">
        <h2>Today's tasks</h2>
        {running.length > 0 ? (
          <>
            <ul className="task-list">
              {running.slice(0, SHOWN_IN_PROGRESS).map((item) => (
                <Task key={item.id} item={item} today={today} />
              ))}
            </ul>
            {running.length > SHOWN_IN_PROGRESS && (
              <Link className="see-all" to="/kanban">
                see all {running.length} on the board
              </Link>
            )}
          </>
        ) : (
          <>
            <p className="muted">Nothing in progress. Nearest by start date:</p>
            <ul className="task-list">
              {suggestedNext(items).map((item) => (
                <Task key={item.id} item={item} today={today} suggested />
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="block">
        <h2>Profile</h2>
        <Radar coverage={dimensionCoverage(items, roadmap)} />
        <ul className="axis-list">
          {dimensionCoverage(items, roadmap).map((entry) => (
            <li key={entry.dimension}>
              <span className="axis-name">{entry.dimension}</span>
              <span className="count">
                {entry.covered}/{entry.total}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="block">
        <h2>
          Skills <span className="count">{covered.length} covered · {pending.length} pending</span>
        </h2>
        {covered.length === 0 ? (
          <p className="muted">Nothing covered yet — a skill counts once an item that teaches it is done.</p>
        ) : (
          <div className="skills">
            {covered.map((skill) => (
              <span key={skill} className="skill covered">
                {skill}
              </span>
            ))}
          </div>
        )}
        <div className="skills">
          {pending.map((skill) => (
            <span key={skill} className="skill">
              {skill}
            </span>
          ))}
        </div>
      </section>
    </div>
  )
}

function Stat({
  label,
  value,
  children,
  bad,
  good,
  wide,
}: {
  label: string
  value: string
  children: React.ReactNode
  bad?: boolean
  good?: boolean
  wide?: boolean
}) {
  const tone = bad ? 'stat-value bad' : good ? 'stat-value good' : 'stat-value'
  return (
    <div className={wide ? 'stat wide' : 'stat'}>
      <div className="stat-label">{label}</div>
      <div className={tone}>{value}</div>
      <div className="stat-note">{children}</div>
    </div>
  )
}

function Task({ item, today, suggested }: { item: Item; today: string; suggested?: boolean }) {
  const late = !suggested && item.projectedEndDate < today
  return (
    <li>
      <span className="type-tag">{item.type}</span>
      <span className="task-name">{item.name}</span>
      <span className={late ? 'task-date bad' : 'task-date'}>
        {suggested ? `starts ${item.projectedStartDate}` : `due ${item.projectedEndDate}`}
      </span>
    </li>
  )
}

function contextValue(context: ReturnType<typeof activeContext>): string {
  if (context.kind === 'blackout') return context.blackout.reason
  if (context.kind === 'phase') return `Phase ${context.phase.number}`
  return 'outside the plan'
}

function paceReading(days: number | undefined): string {
  if (days === undefined) return 'no milestone left'
  if (days === 0) return 'on the original plan'
  return days > 0 ? 'days behind the plan' : 'days ahead of the plan'
}

function signed(days: number): string {
  return days > 0 ? `+${days}d` : `${days}d`
}

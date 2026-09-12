import { Link } from 'react-router-dom'
import {
  activeContext,
  currentStreakWeeks,
  dimensionCoverage,
  inProgress,
  nextMilestone,
  overdueItems,
  skillsByDimension,
  suggestedNext,
  type Context,
} from '../core/dashboard'
import type { AppState, CivilDate, Item } from '../core/types'
import { Radar } from './Radar'

const SHOWN_IN_PROGRESS = 5

/**
 * Three blocks, top down: what today is, how the plan is going, and what the
 * profile looks like. The order is the point — the date and the work in hand
 * are what the page is opened for, so they are not a line in the footer.
 *
 * Progress by phase is deliberately absent: the backlog's sidebar already
 * carries done/total per phase, and a second copy is a second thing to keep
 * true. The radar answers a different question, coverage by skill area.
 */
export function Dashboard({ state }: { state: AppState }) {
  const { items, today, roadmap } = state
  const context = activeContext(today, roadmap, items)
  const streak = currentStreakWeeks(items, today, roadmap.timeZone)
  const late = overdueItems(items, today)
  const milestone = nextMilestone(items, roadmap.phases, today)
  const running = inProgress(items)
  const done = items.filter((item) => item.state === 'done').length
  const groups = skillsByDimension(items, roadmap)

  return (
    <div className="dashboard">
      <section className="block today">
        <div className="today-head">
          <div>
            <div className="today-date">{longDate(today)}</div>
            <div className="today-where">{whereYouAre(context)}</div>
          </div>
          <div className="today-streak">
            <span className="stat-value">{streak === 0 ? '—' : `${streak}w`}</span>
            <span className="stat-label">streak</span>
          </div>
        </div>

        {running.length > 0 ? (
          <>
            <h3>
              In progress <span className="count">{running.length}</span>
            </h3>
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
            <h3>
              Nothing in progress <span className="count">nearest by start date</span>
            </h3>
            <ul className="task-list">
              {suggestedNext(items).map((item) => (
                <Task key={item.id} item={item} today={today} suggested />
              ))}
            </ul>
            <Link className="see-all" to="/backlog">
              pick one in the backlog
            </Link>
          </>
        )}
      </section>

      <section className="block">
        <h2>Progress</h2>
        <div className="stats">
          <Stat label="Roadmap" value={`${done}/${items.length}`}>
            <Meter ratio={items.length === 0 ? 0 : done / items.length} />
          </Stat>

          <Stat label="Overdue" value={String(late.length)} bad={late.length > 0}>
            {late.length === 0 ? 'nothing past its date' : late[0]!.name}
          </Stat>

          <Stat
            label="Next milestone"
            value={milestone ? `${milestone.daysAway}d` : '—'}
            bad={milestone !== null && milestone.daysAway < 0}
          >
            {milestone
              ? `${milestone.item.name} · ${milestone.item.projectedEndDate}`
              : 'all closed'}
          </Stat>

          <Stat
            label="Pace"
            value={milestone ? signed(milestone.paceDays) : '—'}
            bad={milestone !== null && milestone.paceDays > 0}
            good={milestone !== null && milestone.paceDays < 0}
          >
            {paceReading(milestone?.paceDays)}
          </Stat>
        </div>
      </section>

      <section className="block">
        <h2>Profile</h2>
        <div className="profile">
          <Radar coverage={dimensionCoverage(items, roadmap)} />

          <div className="axis-groups">
            {groups.map((group) => (
              <div key={group.dimension} className="axis-group">
                <div className="axis-head">
                  <span className="axis-name">{group.dimension}</span>
                  <span className="count">
                    {group.covered}/{group.total}
                  </span>
                </div>
                <Meter ratio={group.ratio} />
                <div className="skills">
                  {group.skills.map((skill) => (
                    <span
                      key={skill.name}
                      className={skill.covered ? 'skill covered' : 'skill'}
                    >
                      {skill.name}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}

function Meter({ ratio }: { ratio: number }) {
  return (
    <div className="meter">
      <div className="meter-fill" style={{ width: `${Math.round(ratio * 100)}%` }} />
    </div>
  )
}

function Stat({
  label,
  value,
  children,
  bad,
  good,
}: {
  label: string
  value: string
  children: React.ReactNode
  bad?: boolean
  good?: boolean
}) {
  const tone = bad ? 'stat-value bad' : good ? 'stat-value good' : 'stat-value'
  return (
    <div className="stat">
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

/**
 * The civil date read as a date. Noon UTC, so naming the weekday can never
 * land a day off the string it came from.
 */
function longDate(date: CivilDate): string {
  return new Date(`${date}T12:00:00Z`).toLocaleDateString('en', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

function whereYouAre(context: Context): string {
  if (context.kind === 'blackout') return `${context.blackout.reason} — a planned pause`
  if (context.kind === 'phase') return `Phase ${context.phase.number} · ${context.phase.name}`
  return 'outside the planned range'
}

function paceReading(days: number | undefined): string {
  if (days === undefined) return 'no milestone left'
  if (days === 0) return 'on the original plan'
  return days > 0 ? 'days behind the plan' : 'days ahead of the plan'
}

function signed(days: number): string {
  return days > 0 ? `+${days}d` : `${days}d`
}

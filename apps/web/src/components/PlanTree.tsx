/**
 * The proposal, as the tree it is.
 *
 * The API sends work items flat, each naming its parent — a shallow schema is
 * markedly more reliable for the agent to satisfy than a deeply nested one —
 * so the nesting is rebuilt here, the same way the domain layer rebuilds it on
 * the other side.
 */

import type { PlanItem, Proposal } from '../api'

export function PlanTree({ proposal }: { proposal: Proposal }) {
  const children = new Map<string | null, PlanItem[]>()
  for (const item of proposal.items) {
    const key = item.parent_ref
    children.set(key, [...(children.get(key) ?? []), item])
  }

  const render = (parent: string | null, depth: number): React.ReactNode =>
    (children.get(parent) ?? []).map((item) => (
      <div key={item.ref}>
        <Row item={item} depth={depth} storyHours={proposal.story_hours[item.ref]} />
        {render(item.ref, depth + 1)}
      </div>
    ))

  return (
    <div className="plan">
      {render(null, 0)}
      <div className="plan-total">
        {proposal.items.filter((i) => i.type === 'Task').length > 0 ? (
          <>
            {proposal.total_base_hours}h base · <strong>{proposal.total_final_hours}h</strong>{' '}
            buffered
          </>
        ) : (
          <>{proposal.items.length} items · sized in story points</>
        )}
      </div>
    </div>
  )
}

function Row({
  item,
  depth,
  storyHours,
}: {
  item: PlanItem
  depth: number
  storyHours?: string
}) {
  return (
    <div className="plan-row" style={{ paddingLeft: `${depth * 1.1}rem` }}>
      <div className="plan-line">
        <span className={`badge badge-${item.type.toLowerCase()}`}>{label(item.type)}</span>
        <span className="plan-title">{item.title}</span>
        {item.type === 'Task' && (
          <span className={`plan-hours${item.exceeds_maximum ? ' over' : ''}`}>
            {item.base_hours}h → {item.final_hours}h
          </span>
        )}
        {item.type !== 'Task' && item.story_points != null && (
          <span className="plan-hours">{item.story_points} pts</span>
        )}
        {item.type === 'UserStory' && storyHours && storyHours !== '0' && (
          <span className="plan-hours">{storyHours}h total</span>
        )}
      </div>
      {item.description && <p className="plan-desc">{item.description}</p>}
      {item.acceptance_criteria && item.acceptance_criteria.length > 0 && (
        <ul className="plan-criteria">
          {item.acceptance_criteria.map((criterion, index) => (
            <li key={index}>{criterion}</li>
          ))}
        </ul>
      )}
      {(item.sprint || item.kind) && (
        <div className="plan-meta">
          {item.kind && <span>{item.kind.replace(/_/g, ' ')}</span>}
          {item.sprint && <span>{item.sprint}</span>}
        </div>
      )}
    </div>
  )
}

const label = (type: PlanItem['type']) => (type === 'UserStory' ? 'Story' : type)

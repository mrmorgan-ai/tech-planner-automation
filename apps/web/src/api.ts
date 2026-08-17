/**
 * The API, typed.
 *
 * These types are the wire contract, written by hand against the shapes in
 * `adapters/driving/http/serialization.py`. Note that every hour figure is a
 * `string`: JSON numbers are IEEE doubles in the browser, and the backend keeps
 * estimates in `Decimal` precisely so the buffer arithmetic stays exact.
 * Parsing them into numbers here would throw that away on the last hop.
 */

const BASE = '/api'

export type WorkItemType = 'Epic' | 'Feature' | 'UserStory' | 'Task'

export interface PlanItem {
  ref: string
  type: WorkItemType
  title: string
  description: string
  parent_ref: string | null
  sprint: string | null
  iteration_path: string | null
  area: string | null
  assignee: string | null
  priority: number | null
  tags: string[]
  // Tasks only.
  kind?: string
  base_hours?: string
  final_hours?: string
  exceeds_maximum?: boolean
  // Everything above a Task.
  acceptance_criteria?: string[]
  story_points?: number | null
}

export interface Proposal {
  items: PlanItem[]
  total_base_hours: string
  total_final_hours: string
  story_hours: Record<string, string>
}

export interface Violation {
  rule: string
  severity: 'error' | 'warning' | 'info'
  message: string
  item_ref: string | null
}

export interface Report {
  approvable: boolean
  violations: Violation[]
}

export interface CreatedItem {
  ref: string
  backend_id: string
  url: string | null
}

export type SessionStatus =
  | 'drafting'
  | 'proposed'
  | 'rejected'
  | 'approved'
  | 'creating'
  | 'created'
  | 'failed'

export interface Session {
  id: string
  status: SessionStatus
  requirement: string
  scope: string
  levels: WorkItemType[]
  plans_tasks: boolean
  buffer_factor: string
  capacity_hours: string | null
  prompt_revision: string | null
  may_create: boolean
  failure: string | null
  item_count: number
  proposal?: Proposal | null
  report?: Report | null
  decision?: { approved: boolean; note: string; decided_at: string } | null
  created?: CreatedItem[]
  mcp_servers?: string[]
}

export interface Health {
  ok: boolean
  config: string
  backend: string
  profile: string
  runtime: string
  prompt_characters: number
  unfilled_placeholders: string[]
  active_runs: string[]
  mcp_servers?: string[]
  runtime_error?: string
}

export interface PassPolicy {
  permission_mode: string
  exhaustive: boolean
  allowed: string[]
  denied: string[]
}

export interface Policy {
  profile: string
  backend: string
  passes: Record<'propose' | 'create', PassPolicy>
}

export interface ContextFile {
  name: string
  path: string
  size_bytes: number
}

export interface Capacity {
  default_hours: string
  buffer_factor: string
  sprints: Record<string, string>
}

export class ApiError extends Error {
  // Written out rather than as constructor parameter properties: the build
  // runs with `erasableSyntaxOnly`, which allows only type syntax that can be
  // stripped without emitting anything.
  status: number
  detail?: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: init?.body ? { 'content-type': 'application/json' } : undefined,
  })
  if (!response.ok) {
    // The API answers with a `detail` that is either a string or an object
    // carrying the rule violations that blocked an approval. Both are worth
    // surfacing verbatim — they were written to be read by a person.
    const body = await response.json().catch(() => ({}))
    const detail = (body as { detail?: unknown }).detail
    throw new ApiError(response.status, describe(detail) ?? response.statusText, detail)
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

function describe(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const { message, errors } = detail as { message: string; errors?: string[] }
    return errors?.length ? `${message}: ${errors.join('; ')}` : message
  }
  return undefined
}

const post = (body: unknown) => ({ method: 'POST', body: JSON.stringify(body) })
const put = (body: unknown) => ({ method: 'PUT', body: JSON.stringify(body) })

export const api = {
  health: (deep = false) => request<Health>(`/health${deep ? '?deep=true' : ''}`),
  policy: () => request<Policy>('/policy'),

  listSessions: () => request<Session[]>('/sessions'),
  getSession: (id: string) => request<Session>(`/sessions/${id}`),
  createSession: (body: {
    requirement?: string
    cadence?: string | null
    buffer_factor?: string | null
    capacity_hours?: string | null
    sprint?: string | null
  }) => request<Session>('/sessions', post(body)),

  /** `started` is true only when this opened a new session; a continued turn
   *  arrives on the stream that is already attached. */
  sendMessage: (id: string, text: string) =>
    request<{ session_id: string; started: boolean; turn: string }>(
      `/sessions/${id}/messages`,
      post({ text }),
    ),
  approve: (id: string, approved: boolean, note = '') =>
    request<{ session_id: string; approved: boolean }>(
      `/sessions/${id}/approve`,
      post({ approved, note }),
    ),
  cancelRun: (id: string) =>
    request<{ cancelled: boolean }>(`/sessions/${id}/run`, { method: 'DELETE' }),

  readPrompt: () =>
    request<{ text: string; assembled: string; unfilled_placeholders: string[] }>('/prompt'),
  writePrompt: (text: string) =>
    request<{ saved: boolean; characters: number }>('/prompt', put({ text })),

  listContext: () => request<ContextFile[]>('/context'),
  /** Upload real files. A browser never discloses a path, so this sends bytes;
   *  the server writes them to disk and the agent reads a real file. */
  uploadContext: async (files: FileList | File[]): Promise<ContextFile[]> => {
    const form = new FormData()
    for (const file of Array.from(files)) form.append('files', file)
    const response = await fetch(`${BASE}/context/upload`, { method: 'POST', body: form })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new ApiError(response.status, describe((body as { detail?: unknown }).detail) ?? response.statusText)
    }
    return (await response.json()) as ContextFile[]
  },
  attachContext: (path: string, name?: string) =>
    request<ContextFile>('/context', post({ path, name: name || null })),
  detachContext: (name: string) =>
    request<void>(`/context/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  capacity: () => request<Capacity>('/capacity'),
  setCapacity: (sprint: string, hours: string) =>
    request<{ sprint: string; hours: string }>(
      `/capacity/${encodeURIComponent(sprint)}`,
      put({ hours }),
    ),
}

export const eventsUrl = (id: string) => `${BASE}/sessions/${id}/events`

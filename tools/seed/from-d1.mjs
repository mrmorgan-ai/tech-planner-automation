import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'

// Rebuilds seed/roadmap.json from the database. The roadmap is private and not
// in this repository, so D1 is its durable home — this is the way back from the
// database to a file you can edit, on this machine or a new one.
//
//   node tools/seed/from-d1.mjs --remote    (production)
//   node tools/seed/from-d1.mjs --local     (the local dev database)

const target = process.argv[2] ?? '--remote'
if (target !== '--remote' && target !== '--local') {
  console.error(`Expected --remote or --local, got ${target}`)
  process.exit(1)
}

const query = (sql) => {
  const stdout = execFileSync(
    'npx',
    ['wrangler', 'd1', 'execute', 'planify', target, '--json', '--command', sql],
    { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
  )
  // Wrangler may print a banner before the JSON payload.
  const start = stdout.indexOf('[')
  if (start === -1) throw new Error(`No JSON in wrangler output for: ${sql}`)
  return JSON.parse(stdout.slice(start))[0].results
}

const metaRows = query('SELECT key, value FROM meta')
const meta = Object.fromEntries(metaRows.map((row) => [row.key, row.value]))

const parseJson = (value, fallback) => {
  if (value === undefined) return fallback
  try {
    return JSON.parse(value)
  } catch {
    return fallback
  }
}

const roadmap = {
  timeZone: meta.time_zone ?? 'UTC',
  expectedItemsPerPhase: parseJson(meta.expected_items_per_phase, {}),
  phases: query('SELECT number, name, closing_milestone_id FROM phases ORDER BY number').map(
    (row) => ({
      number: row.number,
      name: row.name,
      closingMilestoneId: row.closing_milestone_id ?? null,
    }),
  ),
  blackouts: query('SELECT from_date, to_date, reason FROM blackouts ORDER BY from_date').map(
    (row) => ({ from: row.from_date, to: row.to_date, reason: row.reason }),
  ),
  phaseWindows: parseJson(meta.phase_windows, {}),
  milestoneDependencyExceptions: parseJson(meta.milestone_dependency_exceptions, {}),
  dimensions: query('SELECT name FROM dimensions ORDER BY sort_order').map((row) => row.name),
  // Grouped by axis rather than alphabetically: this file is hand-edited, and
  // the grouping is what makes a 70-skill map readable.
  skills: Object.fromEntries(
    query(
      `SELECT s.name, s.dimension FROM skills s
       JOIN dimensions d ON d.name = s.dimension
       ORDER BY d.sort_order, s.name`,
    ).map((row) => [row.name, row.dimension]),
  ),
  items: query(
    `SELECT id, name, type, phase, skills, depends_on, baseline_start, baseline_end,
            price, link, notes, sort_order
     FROM items ORDER BY phase, sort_order`,
  ).map((row) => ({
    id: row.id,
    name: row.name,
    type: row.type,
    phase: row.phase,
    skills: JSON.parse(row.skills),
    baselineStartDate: row.baseline_start,
    baselineEndDate: row.baseline_end,
    dependsOn: JSON.parse(row.depends_on),
    price: row.price,
    link: row.link ?? null,
    notes: row.notes,
    sortOrder: row.sort_order,
  })),
}

const out = new URL('../../seed/roadmap.json', import.meta.url)
writeFileSync(out, `${JSON.stringify(roadmap, null, 2)}\n`)

console.log(
  `seed/roadmap.json — ${roadmap.items.length} items, ${roadmap.phases.length} phases, ` +
    `${Object.keys(roadmap.skills).length} skills, from ${target.slice(2)} D1`,
)

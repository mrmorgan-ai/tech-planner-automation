# Planify

A tracker for a long study roadmap: items grouped in phases, with real
dependencies between them and automatic date recalculation when something slips.
Single user, no accounts.

It shows the original plan and the live projection on the same bar, so the
question it answers is "am I ahead or behind today?" rather than "what were the
dates again?".

## The app is open, the roadmap is not

This repository carries the application: the recalculation engine, the API, the
web app and the validator. It deliberately carries no roadmap content — no
items, no phase names, no dates, no non-study periods, no skill map. All of that
is personal, so it lives in the D1 database and in a gitignored seed file.

`seed/roadmap.example.json` is tracked. It is a small fake roadmap that
documents the file's shape and is what CI validates the rules against without
ever seeing the real one.

## Stack

React + Vite on Cloudflare Pages, the API as Pages Functions, Cloudflare D1
(serverless SQLite) for persistence. Access control is Cloudflare Access at the
platform level, so there is no login code here.

## Layout

```
src/core/               pure TypeScript: types, dates, recalculation engine
src/server/             backend helpers that touch the clock
src/ui/                 the React app
functions/api/          route handlers, one file per endpoint
tools/seed/             validator, SQL emitter, and the export back from D1
migrations/             D1 schema, applied with wrangler
seed/roadmap.json       the roadmap — gitignored, never committed
```

`src/core/` is compiled by both `tsconfig.json` (DOM libs, for the UI) and
`tsconfig.worker.json` (Workers types, for the API). That is deliberate: it makes
the compiler enforce that the core stays platform-neutral, which is what lets the
engine be tested with plain fixtures.

The core takes its calendar as an argument — `{ blackouts, timeZone }` — and
never reads a global. That is the same rule seen from the inside: content comes
from the database, not from this repository.

## Running it locally

```bash
npm install
cp seed/roadmap.example.json seed/roadmap.json   # or export the real one, below
npm run seed:validate
npm run seed:sql
npm run db:migrate:local
npx wrangler d1 execute planify --local --file build/seed.sql
npm run dev:api                                   # Workers runtime + local D1 on 8788
npm run dev                                       # the web app on 5173, in another terminal
```

`http://127.0.0.1:5173` should show the nav with a green line at the bottom
reporting today's date and the item count in D1.

Checks: `npm run typecheck` · `npm test` · `npm run build`. Run them without a
pipe — piping hides the exit code and a failing gate then looks green.

## The seed

Content flows in one direction for a load and the other for a restore.

```bash
npm run seed:validate                             # every rule, on every seed file present
npm run seed:sql                                  # -> build/seed.sql (upsert)
npx wrangler d1 execute planify --file build/seed.sql --remote
curl -X POST https://<your-domain>/api/reproject  # recompute projections
```

The upsert updates content and deliberately never touches `state`,
`completed_at` or the projected dates, so reloading the seed cannot overwrite
progress.

```bash
npm run seed:export                               # D1 -> seed/roadmap.json
```

That is the way back. The database is the durable home of the roadmap, so a new
machine — or a lost disk — recovers the whole seed, including the metadata the
validator checks it against.

The strongest rule in the validator is that with nothing completed, the engine
must project every item exactly onto its own baseline. If a dependency ends on
or after the baseline start of something that waits on it, the plan would be born
already slipped, and the validator says which item.

## Cloudflare setup (once, not automated)

`wrangler.toml` and `migrations/` are the infrastructure as code for the Pages
project and the database. The two things wrangler cannot express are done by hand
in the dashboard and written down here instead of in Terraform — three resources
for a single-user app do not pay for their own state file.

1. `npx wrangler d1 create planify` — copy the returned id into `wrangler.toml`,
   replacing the placeholder `database_id`.
2. `npm run db:migrate` — applies the schema to the remote database.
3. Create the Pages project (dashboard → Workers & Pages → Pages), connect this
   repository, build command `npm run build`, output directory `dist`.
4. Bind the D1 database to the Pages project as `DB`, in both production and
   preview.
5. Cloudflare Access → add an application covering the project's domain, with a
   policy allowing exactly one identity. This is what makes the app private;
   there is no application-level auth to fall back on.

Revisit the by-hand decision if a second environment ever appears, or if the
project has to be recreated from scratch.

## License

MIT — see [LICENSE](LICENSE).

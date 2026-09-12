-- Planify schema. Shape only. Every row of content — the items, the phase
-- names, the non-study periods, the radar axes and the skill map — is loaded
-- separately from a seed that is deliberately not part of this repository.

CREATE TABLE items (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  type            TEXT NOT NULL CHECK (type IN ('Certification','Course','Book','Documentation','Paper','Case study','Project')),
  phase           INTEGER NOT NULL CHECK (phase BETWEEN 1 AND 6),

  -- JSON arrays. The engine always loads the whole graph, so join tables would
  -- buy queryability nothing in this app needs.
  skills          TEXT NOT NULL DEFAULT '[]',
  depends_on      TEXT NOT NULL DEFAULT '[]',

  -- The original plan. Immutable once seeded; drift is measured against it.
  baseline_start  TEXT NOT NULL,
  baseline_end    TEXT NOT NULL,

  -- The live projection. The only columns the recalculation engine writes.
  projected_start TEXT NOT NULL,
  projected_end   TEXT NOT NULL,

  price           TEXT NOT NULL DEFAULT '',
  link            TEXT,
  notes           TEXT NOT NULL DEFAULT '',

  state           TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','in_progress','done')),
  completed_at    TEXT,

  -- Curated dependency order inside a phase. Topological order is not unique,
  -- so the backlog's order is a seed decision, not something derivable.
  sort_order      INTEGER NOT NULL,

  CHECK (baseline_end >= baseline_start),
  CHECK (projected_end >= projected_start),
  CHECK ((state = 'done') = (completed_at IS NOT NULL))
);

CREATE INDEX idx_items_phase_order ON items (phase, sort_order);

-- Six fixed phases. The count is application structure; the names are content.
CREATE TABLE phases (
  number               INTEGER PRIMARY KEY CHECK (number BETWEEN 1 AND 6),
  name                 TEXT NOT NULL,
  -- Not derivable from an item's type: a phase with no certification closes on
  -- a deliverable instead. Null for a phase that closes on nothing.
  closing_milestone_id TEXT REFERENCES items (id)
);

-- Non-study periods. The engine skips them when projecting dates.
CREATE TABLE blackouts (
  from_date TEXT PRIMARY KEY,
  to_date   TEXT NOT NULL,
  reason    TEXT NOT NULL,
  CHECK (to_date >= from_date)
);

-- The radar's axes.
CREATE TABLE dimensions (
  name       TEXT PRIMARY KEY,
  sort_order INTEGER NOT NULL UNIQUE
);

-- Each granular skill belongs to exactly one axis, which the primary key
-- enforces: a skill counted twice would break the radar's denominator.
CREATE TABLE skills (
  name      TEXT PRIMARY KEY,
  dimension TEXT NOT NULL REFERENCES dimensions (name)
);

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT INTO meta (key, value) VALUES
  ('seed_version', '0'),
  ('revision', '0'),
  ('time_zone', 'UTC');

-- Three additions, all driven by the backlog becoming editable.
--
-- `duration` and `resources` pull apart what the seed used to keep in one
-- `notes` string: how long a thing takes, the extra links it carries, and the
-- description. One field holding three answers reads badly in every view.
--
-- `start_date` is the roadmap's anchor. Baseline dates stop being immutable
-- once they can be edited, so the plan needs a floor nothing may be moved
-- before — without one, a typo in an edit silently reschedules the past.

ALTER TABLE items ADD COLUMN duration TEXT NOT NULL DEFAULT '';

-- A JSON array of { label, url }. Same reasoning as skills and depends_on: the
-- engine loads the whole graph anyway, so a join table buys nothing here.
ALTER TABLE items ADD COLUMN resources TEXT NOT NULL DEFAULT '[]';

INSERT INTO meta (key, value) VALUES ('start_date', '')
ON CONFLICT(key) DO NOTHING;

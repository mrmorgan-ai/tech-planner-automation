-- Study capacity per week, so the board can say how much of a week is already
-- committed. Content, not application: the numbers are personal, which is why
-- they live here and not in the source.
--
-- Defaults are empty on purpose. A capacity the app invented would read as the
-- owner's own figure, and an hours count built on an invented number is worse
-- than no hours count.

INSERT INTO meta (key, value) VALUES
  ('weekly_hours_normal', ''),
  ('weekly_hours_last_week', '')
ON CONFLICT(key) DO NOTHING;

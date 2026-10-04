-- Local copy of upcoming iCloud events so api and other agents can read them
-- without holding iCloud credentials. iCloud stays the source of truth.
CREATE TABLE calendar_events (
  id SERIAL PRIMARY KEY,
  uid TEXT NOT NULL,                  -- iCalendar UID; shared by every instance of a recurring event
  calendar_name TEXT NOT NULL,
  title TEXT NOT NULL,
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ,
  all_day BOOLEAN NOT NULL DEFAULT false,
  location TEXT,
  synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- starts_at is part of the key because recurring instances share a uid.
  UNIQUE (calendar_name, uid, starts_at)
);

CREATE INDEX calendar_events_starts_at_idx ON calendar_events (starts_at);

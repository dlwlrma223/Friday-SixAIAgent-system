-- A calendar write waiting for approval. The dashboard or any agent may ask;
-- only the calendar agent writes to iCloud, and only once approved.
CREATE TABLE calendar_event_requests (
  id SERIAL PRIMARY KEY,
  requested_by INT REFERENCES agents(id),   -- NULL = created by me on the dashboard
  -- Chosen up front so a retried write updates the same event instead of duplicating it.
  event_uid TEXT NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ NOT NULL,
  all_day BOOLEAN NOT NULL DEFAULT false,
  location TEXT CHECK (location IS NULL OR length(location) <= 200),
  notes TEXT CHECK (notes IS NULL OR length(notes) <= 2000),
  reason TEXT,                              -- why an agent wants this event
  status TEXT NOT NULL DEFAULT 'pending_approval'
    CHECK (status IN ('pending_approval', 'written', 'skipped', 'failed')),
  approval_id INT REFERENCES approvals(id),
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  CHECK (ends_at >= starts_at)
);

-- The agent only ever looks for undecided rows.
CREATE INDEX calendar_event_requests_pending_idx
  ON calendar_event_requests (status) WHERE status = 'pending_approval';

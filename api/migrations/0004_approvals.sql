-- Every external side effect waits here as 'pending' until approved.
CREATE TABLE approvals (
  id SERIAL PRIMARY KEY,
  agent_id INT REFERENCES agents(id),
  title TEXT NOT NULL,
  detail TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'approved', 'skipped')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

-- Dashboard only ever lists pending rows; partial index keeps it tiny.
CREATE INDEX approvals_status_idx ON approvals (status) WHERE status = 'pending';

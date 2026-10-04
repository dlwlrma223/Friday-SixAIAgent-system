-- A sentence I typed for the calendar agent ("dinner with Ming next Wed 7pm").
-- The agent turns it into a calendar_event_requests row, which still needs approval.
CREATE TABLE calendar_intents (
  id SERIAL PRIMARY KEY,
  text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 500),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'drafted', 'failed')),
  request_id INT REFERENCES calendar_event_requests(id),  -- set once drafted
  error TEXT,                                             -- shown to me when it failed
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

-- The agent only ever looks for rows it has not handled yet.
CREATE INDEX calendar_intents_pending_idx ON calendar_intents (status) WHERE status = 'pending';

-- Something I want to learn ("I want to pass CCNA"), and the plan the study
-- agent wrote for it from web research.
CREATE TABLE study_goals (
  id SERIAL PRIMARY KEY,
  subject_id INT REFERENCES subjects(id),
  request_text TEXT NOT NULL CHECK (length(request_text) BETWEEN 1 AND 500),
  title TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'planned', 'failed')),
  overview TEXT,
  facts JSONB NOT NULL DEFAULT '[]',     -- [{label, value}] e.g. exam code, format, pass mark
  total_weeks INT CHECK (total_weeks IS NULL OR total_weeks BETWEEN 1 AND 104),
  sources JSONB NOT NULL DEFAULT '[]',   -- [{id, title, url}] the plan was written from
  error TEXT,                            -- shown to me when planning failed
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

-- The agent only ever looks for goals it has not planned yet.
CREATE INDEX study_goals_pending_idx ON study_goals (status) WHERE status = 'pending';

CREATE TABLE job_applications (
  id SERIAL PRIMARY KEY,
  company TEXT,
  position TEXT,
  jd_text TEXT,
  match_score NUMERIC,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'pending_approval', 'submitted', 'rejected')),
  applied_at TIMESTAMPTZ
);

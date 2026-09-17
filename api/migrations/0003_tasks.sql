CREATE TABLE tasks (
  id SERIAL PRIMARY KEY,
  agent_id INT REFERENCES agents(id),
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'in_progress', 'done', 'waiting_on_you')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

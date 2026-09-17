-- Audit log: every Research call, whether or not it was actually sent.
CREATE TABLE research_queries (
  id SERIAL PRIMARY KEY,
  agent_id INT REFERENCES agents(id),     -- which agent asked
  query TEXT NOT NULL,
  purpose TEXT,
  pii_flags TEXT[] NOT NULL DEFAULT '{}', -- guard rules that matched, empty = clean
  status TEXT NOT NULL DEFAULT 'sent'
    CHECK (status IN ('sent', 'pending_approval', 'approved_sent', 'skipped', 'failed')),
  approval_id INT REFERENCES approvals(id),
  result_count INT,
  answer_preview TEXT,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX research_queries_created_at_idx ON research_queries (created_at DESC);
CREATE INDEX research_queries_agent_id_idx ON research_queries (agent_id);

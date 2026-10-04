-- One row per LLM call, so I can see what each agent spends and cap it.
CREATE TABLE llm_usage (
  id SERIAL PRIMARY KEY,
  purpose TEXT NOT NULL,                 -- study_plan / study_material / ...
  model TEXT NOT NULL,
  input_tokens INT NOT NULL DEFAULT 0,
  output_tokens INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX llm_usage_created_at_idx ON llm_usage (created_at DESC);

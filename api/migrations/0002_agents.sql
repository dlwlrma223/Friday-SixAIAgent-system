CREATE TABLE agents (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,          -- calendar / home / research / study / finance / jobs
  status TEXT NOT NULL DEFAULT 'idle'
);

-- Seed. ON CONFLICT keeps this safe if the seed is ever re-run.
INSERT INTO agents (name) VALUES
  ('calendar'), ('home'), ('research'), ('study'), ('finance'), ('jobs')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE subjects (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

INSERT INTO subjects (name) VALUES
  ('English'), ('Japanese'), ('taxi license'), ('electrician'), ('AWS SAA')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE study_sessions (
  id SERIAL PRIMARY KEY,
  subject_id INT REFERENCES subjects(id),
  duration_minutes INT CHECK (duration_minutes > 0),
  self_rating INT CHECK (self_rating BETWEEN 1 AND 5),
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

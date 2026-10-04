-- One chapter of a study plan. Cards, quizzes and notes hang off these later.
CREATE TABLE study_modules (
  id SERIAL PRIMARY KEY,
  goal_id INT NOT NULL REFERENCES study_goals(id) ON DELETE CASCADE,
  position INT NOT NULL CHECK (position >= 1),
  title TEXT NOT NULL,
  summary TEXT,
  topics TEXT[] NOT NULL DEFAULT '{}',
  est_hours NUMERIC CHECK (est_hours IS NULL OR est_hours > 0),
  week INT CHECK (week IS NULL OR week >= 1),
  source_ids INT[] NOT NULL DEFAULT '{}',  -- ids into study_goals.sources
  UNIQUE (goal_id, position)
);

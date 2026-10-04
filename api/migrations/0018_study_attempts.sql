-- Every answer I give. Spaced repetition (4d) will be driven by this.
CREATE TABLE study_attempts (
  id SERIAL PRIMARY KEY,
  question_id INT NOT NULL REFERENCES study_questions(id) ON DELETE CASCADE,
  chosen_index INT NOT NULL CHECK (chosen_index BETWEEN 0 AND 3),
  is_correct BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX study_attempts_question_idx ON study_attempts (question_id, created_at DESC);

-- Multiple-choice questions for one module. Always four options.
CREATE TABLE study_questions (
  id SERIAL PRIMARY KEY,
  module_id INT NOT NULL REFERENCES study_modules(id) ON DELETE CASCADE,
  position INT NOT NULL CHECK (position >= 1),
  question TEXT NOT NULL,
  options JSONB NOT NULL CHECK (jsonb_typeof(options) = 'array' AND jsonb_array_length(options) = 4),
  correct_index INT NOT NULL CHECK (correct_index BETWEEN 0 AND 3),
  explanation TEXT,
  UNIQUE (module_id, position)
);

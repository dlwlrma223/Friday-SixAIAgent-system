-- Flash cards for one module, written by the study agent.
CREATE TABLE study_cards (
  id SERIAL PRIMARY KEY,
  module_id INT NOT NULL REFERENCES study_modules(id) ON DELETE CASCADE,
  position INT NOT NULL CHECK (position >= 1),
  front TEXT NOT NULL,
  back TEXT NOT NULL,
  UNIQUE (module_id, position)
);

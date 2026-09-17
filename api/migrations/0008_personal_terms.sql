-- Terms that must never leave the system inside a search query (my name,
-- address, employer...). Values live here, never in code.
CREATE TABLE personal_terms (
  id SERIAL PRIMARY KEY,
  term TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL DEFAULT 'other'
    CHECK (category IN ('name', 'address', 'employer', 'account', 'other')),
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

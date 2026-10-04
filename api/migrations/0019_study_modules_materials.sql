-- Cards and questions are generated per module, on request.
ALTER TABLE study_modules
  ADD COLUMN materials_status TEXT NOT NULL DEFAULT 'none'
    CHECK (materials_status IN ('none', 'pending', 'ready', 'failed')),
  ADD COLUMN materials_error TEXT,                       -- shown to me when generation failed
  ADD COLUMN materials_sources JSONB NOT NULL DEFAULT '[]';  -- [{id, title, url}]

-- The agent only ever looks for modules waiting for materials.
CREATE INDEX study_modules_materials_pending_idx
  ON study_modules (materials_status) WHERE materials_status = 'pending';

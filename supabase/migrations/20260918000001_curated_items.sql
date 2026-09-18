-- Curated, scored source items produced by the manual ingestion engine.
-- Backend-only: the service role bypasses RLS; anon/authenticated callers
-- receive no access because this table intentionally has no policies.
CREATE TABLE IF NOT EXISTS curated_items (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type          VARCHAR(20) NOT NULL,
  source_ref           VARCHAR(200),
  region               VARCHAR(2),
  title                TEXT NOT NULL,
  summary              TEXT NOT NULL,
  raw_text             TEXT,
  category             VARCHAR(20) NOT NULL,
  recency_score        INTEGER,
  popularity_score     INTEGER,
  cultural_weight      INTEGER,
  evergreen_value      INTEGER,
  priority_score       INTEGER,
  challenge_notes      TEXT,
  pipeline_decision    VARCHAR(20),
  lifespan_days        INTEGER,
  refresh_frequency_days INTEGER,
  decay_rate           DOUBLE PRECISION,
  auto_archive         BOOLEAN NOT NULL DEFAULT FALSE,
  expires_at           TIMESTAMPTZ,
  created_at           TIMESTAMPTZ DEFAULT NOW(),
  updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_curated_items_source_type ON curated_items(source_type);
CREATE INDEX IF NOT EXISTS ix_curated_items_source_ref ON curated_items(source_ref);
CREATE INDEX IF NOT EXISTS ix_curated_items_region ON curated_items(region);
CREATE INDEX IF NOT EXISTS ix_curated_items_category ON curated_items(category);
CREATE INDEX IF NOT EXISTS ix_curated_items_priority_score ON curated_items(priority_score);
CREATE INDEX IF NOT EXISTS ix_curated_items_pipeline_decision ON curated_items(pipeline_decision);
CREATE INDEX IF NOT EXISTS ix_curated_items_expires_at ON curated_items(expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_curated_items_source_key
  ON curated_items(source_type, source_ref);

ALTER TABLE curated_items ENABLE ROW LEVEL SECURITY;

DROP TRIGGER IF EXISTS set_curated_items_updated_at ON curated_items;
CREATE TRIGGER set_curated_items_updated_at
  BEFORE UPDATE ON curated_items
  FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();
CREATE TABLE IF NOT EXISTS generated_content (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL,
  generated_at  TIMESTAMPTZ DEFAULT NOW(),
  trend_date    DATE DEFAULT CURRENT_DATE,
  clusters      JSONB DEFAULT '[]',
  content_ideas JSONB DEFAULT '[]',
  delivered     BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_generated_content_user ON generated_content(user_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_generated_content_date ON generated_content(trend_date DESC);

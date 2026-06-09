CREATE TABLE IF NOT EXISTS generated_content (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  generated_at  TIMESTAMPTZ DEFAULT NOW(),
  trend_date    DATE DEFAULT CURRENT_DATE,
  clusters      JSONB DEFAULT '[]',
  content_ideas JSONB DEFAULT '[]',
  delivered     BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_generated_content_user ON generated_content(user_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_generated_content_date ON generated_content(trend_date DESC);

-- RLS: users can read their own digests; pipeline writes via service role
ALTER TABLE generated_content ENABLE ROW LEVEL SECURITY;

CREATE POLICY "content_select_own" ON generated_content
  FOR SELECT USING (auth.uid() = user_id);

CREATE TABLE IF NOT EXISTS raw_signals (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source       TEXT NOT NULL,  -- 'reddit'|'tiktok'|'youtube'|'xhs'|'twitter'
  external_id  TEXT,
  content_text TEXT,
  author       TEXT,
  url          TEXT,
  likes        INT DEFAULT 0,
  comments     INT DEFAULT 0,
  shares       INT DEFAULT 0,
  views        INT DEFAULT 0,
  language     TEXT DEFAULT 'en',
  region       TEXT,
  hashtags     TEXT[],
  audio_title  TEXT,
  collected_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_signals_source_collected ON raw_signals(source, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_signals_collected ON raw_signals(collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_signals_language ON raw_signals(language);

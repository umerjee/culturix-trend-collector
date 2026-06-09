CREATE TABLE IF NOT EXISTS user_profiles (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL,  -- references Supabase auth.users(id)
  target_age_min   INT DEFAULT 18,
  target_age_max   INT DEFAULT 35,
  target_platforms TEXT[] DEFAULT '{}',
  target_regions   TEXT[] DEFAULT '{}',
  content_goals    TEXT[] DEFAULT '{}',
  content_tones    TEXT[] DEFAULT '{}',
  industry_niche   TEXT,
  persona_tags     TEXT[] DEFAULT '{}',
  delivery_freq    TEXT DEFAULT 'daily',
  delivery_time    TIME DEFAULT '07:00:00',
  updated_at       TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles(user_id);

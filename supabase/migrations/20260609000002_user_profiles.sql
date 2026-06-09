CREATE TABLE IF NOT EXISTS user_profiles (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
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

-- Auto-update updated_at on row change
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS set_user_profiles_updated_at ON user_profiles;
CREATE TRIGGER set_user_profiles_updated_at
  BEFORE UPDATE ON user_profiles
  FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();

-- RLS: users can only touch their own profile
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "profiles_select_own" ON user_profiles
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "profiles_insert_own" ON user_profiles
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "profiles_update_own" ON user_profiles
  FOR UPDATE USING (auth.uid() = user_id);

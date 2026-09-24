-- Backfills real drift on the two dual-tracked tables found in the 2026-09-24 audit:
-- Supabase's user_profiles/generated_content have been missing these columns since they
-- were added to Railway's copy (via app/main.py's lifespan ALTER TABLE block) without a
-- matching migration ever being added here. Nothing currently reads Supabase's copy of
-- either table (culturix-web talks to Railway's API for all of this; Supabase is Auth-
-- only in practice — see this directory's README.md), so this closes the drift rather
-- than fixes a live bug, in case that ever changes.
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS approved BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS plan VARCHAR(20) NOT NULL DEFAULT 'free';
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255);
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255);
ALTER TABLE generated_content ADD COLUMN IF NOT EXISTS content_profile_id UUID;

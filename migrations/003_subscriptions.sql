CREATE TABLE IF NOT EXISTS subscriptions (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL,
  status     TEXT DEFAULT 'active',  -- active | paused | cancelled
  plan       TEXT DEFAULT 'free',
  started_at TIMESTAMPTZ DEFAULT NOW(),
  renews_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);

-- Run in Supabase SQL editor or your Postgres instance
-- Note: if using Supabase Auth, the auth.users table already exists.
-- This table mirrors it for application-level data.

CREATE TABLE IF NOT EXISTS users (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email      TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  plan       TEXT DEFAULT 'free'  -- free | pro | enterprise
);

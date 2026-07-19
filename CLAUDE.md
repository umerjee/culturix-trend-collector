# Culturix — Project Instructions for Claude Code

*Auto-refreshed by a scheduled Cowork task. Last scan: 2026-07-19 (last commit: `d9d5e3b`).*

This file replaces `IMPLEMENTATION.md` and `CONTENT_ENGINE_PLAN.md` as the source of truth — those two describe an earlier/aspirational design that has since diverged from what's actually built. Keep this file, not those.

## 1. What Culturix actually is (verified against code, not docs)

A content-intelligence platform: collects social trends, clusters them, generates personalized content ideas per user, lets Pro users generate voiceover/music/video for those ideas, and audits older ideas daily for staleness.

## 2. Current architecture

**Backend** — single FastAPI app (`app/main.py`), Postgres via SQLAlchemy (`DATABASE_URL`, Supabase-hosted), deployed on Railway (`railway.toml`, `uvicorn app.main:app`).

**Collectors** (`app/collectors/`) — Reddit (PRAW), TikTok, YouTube (official API + graceful-degradation message when disabled), Twitter (official API + Jina.ai/trends24.in proxy fallback — note: `twitter.py` and `twitter_apify.py` both exist, see gap #2 below), Xiaohongshu (Apify). `orchestrator.py` runs them together; `/collect/all` and `/admin/collect` trigger manually.

**Pipeline** (`app/pipeline/graph.py`, LangGraph) — `translate_signals → load_signals → embed_signals → cluster_and_persist → generate_personas → cluster_trends → map_personas → generate_content → write_digests`.
- Embeddings: Voyage.ai, stored/searched in Qdrant.
- Clustering: two paths coexist — `legacy_cluster.py` (HDBSCAN, feeds the admin-facing `Cluster`/`Persona` tables) and `clusterer.py` (Voyage+Qdrant+DeepSeek/Claude, feeds actual content-generation matching). See gap #7.
- Content generation (`content_strategist.py`): Qwen-max (Dashscope) primary, Claude Haiku fallback. Generates **10 ideas per content profile**, each with: `hook, caption, cta, music_mood, platform, trend_connection, format, video_prompt, viral_angle, posting_time, hashtag_strategy`. This is richer than what either legacy doc described.
- `digest_writer.py`: persists to `generated_content.content_ideas` (JSONB) and emails via Resend if `RESEND_API_KEY` is set.

**Scheduling** — in-process APScheduler (`app/scheduler.py`): collection 4×/day (01:00/07:00/13:00/19:00 UTC), full pipeline daily 07:00 UTC, Content Check daily 09:00 UTC. Backed up by Railway Cron + a GitHub Actions Supabase-keepalive workflow (prevents free-tier cluster suspension).

**Content Check** (`app/pipeline/nodes/content_check.py`) — confirmed fully wired: scores each idea (trend relevance 50%, platform freshness 30%, persona fit 20%) and writes `status`/`relevance_score` **directly into the idea's JSONB**, which is exactly what `DigestCard.tsx`'s `STATUS_BADGE` reads. No gap here — this loop is closed correctly.

**Media generation** (`app/media/`) — fully implemented, not stubbed: `ElevenLabsProvider` (voiceover), `SunoProvider` (music, via aimlapi.com), `KlingProvider` (video, JWT-signed). Gated: free plan blocked, pro plan capped at 50/month, superadmin bypasses via `SUPERADMIN_USER_ID`. Wired end-to-end through `POST /api/generate-media` → background task → provider → Supabase storage → poll endpoint → `MediaPreview.tsx` in the dashboard. `DigestCard.tsx` has live voiceover/music/video buttons.

**Data model** — `users`, `user_profiles` (approval gate — `approved` boolean, admin-approved via `/admin/users/{id}/approve`), `content_profiles` (multi-niche per user; free=1, pro=10, enforced in `main.py`), `trends`/`raw_signals`, `clusters`, `personas`, `generated_content`, `generated_media`, `content_check_log`. Migrations live in both `/migrations` and `/supabase/migrations` (keep them in sync manually — no single migration tool owns both).

**Frontends — two separate Next.js 14 apps:**
- `culturix-web/` — the real product: signup, onboarding wizard, dashboard (`DigestCard`, `MediaPreview`, `PersonaChips`), settings, an in-app `AdminDashboard.tsx` component, Supabase Auth, password reset flow. Deployed to Vercel.
- `dashboard/` — a separate internal Next.js app (trends/clusters/personas/search browsing via `lib/api.ts`). Overlaps significantly with `AdminDashboard.tsx` inside `culturix-web` — see gap #6.

**Plans** — free/pro exist as a DB field (`user_profiles.plan`), gating content-profile count and media quota. **No self-serve billing** — plan changes are admin-only via `POST /admin/users/{id}/plan`. See gap #1.

## 3. Known gaps / prioritized next steps

1. **No billing/checkout flow.** `plan` is admin-set only (no Stripe or equivalent found anywhere in the repo). This blocks real monetization — highest priority if the goal is paying users.
2. **Duplicate Twitter collectors** — `app/collectors/twitter.py` (124 lines, official API) and `twitter_apify.py` (111 lines) both exist alongside the Jina-proxy fallback in `main.py`. Confirm which is actually live, remove the dead one.
3. **Repo-root clutter** — `debug_clustering.py`, `debug_import_app_clustering.py`, `debug_run_twitter.py`, `debug_twitter_api.py`, `debug_youtube_api.py`, `drop_trends.py`, `print_personas_debug.py`, `test_trends.py` all sit at repo root alongside `scripts/` which already holds ~15 more `debug_*.py` files. Consolidate into `scripts/` or delete.
4. **Stale planning docs** — `IMPLEMENTATION.md` and `CONTENT_ENGINE_PLAN.md` (and the separate `CULTURIX_LAUNCH_BUILD_INSTRUCTIONS.md` in Cowork's outputs, if you save it here) describe designs that no longer match reality per section 2 above. Either delete them or mark them archived so future sessions don't treat them as current.
5. **No automated tests found anywhere** in `app/`, `culturix-web/`, or `dashboard/`. Given how much money-relevant logic exists (plan gating, media quota, billing-adjacent code), at least cover: plan/quota enforcement in `main.py`, `content_check.py` scoring math, and the collector orchestrator's error handling.
6. **`dashboard/` vs `AdminDashboard.tsx` overlap** — two separate UIs both browse trends/clusters/personas. Decide whether `dashboard/` is still maintained or should be retired in favor of the in-app admin component.
7. **Two clustering paths** (`legacy_cluster.py` HDBSCAN vs `clusterer.py` Voyage+Qdrant+DeepSeek) run in the same pipeline for different purposes (admin tables vs content matching). Confirm this dual-path is intentional long-term or if `legacy_cluster.py` should be retired now that the newer path is stable.
8. **Migrations live in two places** (`/migrations` and `/supabase/migrations`) with no tooling enforcing they match — verify they're actually identical before the next schema change, or pick one and delete the other.

## 4. Notes for whoever (human or Claude Code) picks this up

- Don't re-read `IMPLEMENTATION.md`/`CONTENT_ENGINE_PLAN.md` as current-state references — they're historical/aspirational, not accurate. This file supersedes them.
- This file is regenerated periodically by a scheduled task that re-scans the repo — manual edits may be overwritten on the next scan. If you want something to persist, note it clearly or move it to a separate doc.

# Culturix — Project Instructions for Claude Code

*Auto-refreshed by a scheduled Cowork task. Last scan: 2026-07-19 (last commit: `d9d5e3b`).*

This file replaces `IMPLEMENTATION.md` and `CONTENT_ENGINE_PLAN.md` as the source of truth — those two describe an earlier/aspirational design that has since diverged from what's actually built. Keep this file, not those.

> ## ⚠️ VIDEO GENERATION: read `docs/culturix-video-pipeline.md` first
>
> The self-hosted video path moved to **LTX-2.5** on 2026-09-02 (behind
> `LTX_MODEL_VERSION=2.5`). It generates **synchronized audio natively** and
> needs **no character LoRAs** — identity comes from a composite first-frame
> anchor built from the cast's portraits.
>
> `docs/culturix-video-pipeline.md` is **hand-maintained and must not be
> deleted or overwritten by this file's scheduled regeneration.** It holds
> the operational runbook, the environment variables, and — most importantly
> — a *Recurring failure patterns* section covering bugs that have already
> cost multiple days and recurred because nobody wrote them down:
> generated-but-never-read fields, prompts inventing data the DB already has,
> `verify_exists()` checking the same volume it just wrote to, running
> workers not pulling rebuilt images, and the two RunPod Network Volumes
> (`RUNPOD_NETWORK_VOLUME_ID` ≠ `RUNPOD_INFERENCE_NETWORK_VOLUME_ID`) that
> silently diverged for three days.
>
> Anything in the section below describing per-shot LTX generation, Chatterbox
> narration muxing, or LoRA-gated self-hosted video describes the **LTX-2.3**
> path, which is now the fallback.

## 1. What Culturix actually is (verified against code, not docs)

Publicly, Culturix is an AI-generated video encyclopedia of the world with a sense of humour: a source-linked, map-first atlas of history, heritage, science, technology, and culture. The public homepage is viewer-first and should not promise visitor creation access, creator plans, pricing, daily briefs, or self-serve publishing.

Internally, the platform still contains the earlier content-intelligence and creator-generation workflows: it collects social trends, clusters them, generates personalized content ideas per user, supports Pro media generation, and audits older ideas daily for staleness. Treat those as internal/product infrastructure unless the public positioning is deliberately changed again.

**Public homepage positioning (2026-09-29):** `culturix-web/src/app/page.tsx` presents “The world, explained in short videos with a sense of humour,” links visitors to `/world`, uses source-linked atlas language, and replaces creator/pricing sections with place/theme/time exploration. `MarketingHeader.tsx` no longer exposes creator or pricing navigation and uses “Explore the atlas” as the public CTA. Keep the page responsive for phone and iPad widths.

**Localization direction (2026-09-29):** The requested target is English, French, German, and Spanish for the public site plus the signed-in user dashboard; the protected admin console can remain English initially. The backend already has Google-backed translation through `app/translation/` for World summaries, trend digests, transcripts, and narration, with caching and graceful English fallback. Do not introduce a second translation engine for those dynamic fields. Static UI copy still needs a shared frontend dictionary/locale selector; do not translate ad hoc per component.

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
- `culturix-web/` — the real product: signup, onboarding wizard, dashboard (`DigestCard`, `MediaPreview`, `PersonaChips`), settings, the routed superadmin console under `src/app/admin/`, Supabase Auth, and password reset flow. Deployed to Vercel.
- Public homepage/world mode — the public entry point is the viewer-only `/` → `/world` experience. Do not reintroduce “Get started free,” creator pricing, daily brief, Shopify Reel, or Character-Based Posting CTAs on the homepage while creation access is intentionally closed.
- Language scope — public homepage, World atlas/region/feature pages, shared marketing navigation, and signed-in user dashboard/user-mode CultureToons are the next localization surface in `en`, `fr`, `de`, and `es`; admin remains English until explicitly expanded.
- CultureToons user mode (`/dashboard/culturetoons`) and admin mode (`/admin/comedy-videos`, sidebar label "Comedy studio") share `CultureToonApp` and the same owner-scoped `/api/culturetoons/**` proxies. The admin route loads brands for the authenticated superadmin's own Supabase user ID and exposes the full producer workflow: characters, scripts, toons/video generation, episodes, relationships, locations, usage/budget, and the World source library. Admin starts on the Toons tab; user mode remains character-first. Brand API failures must remain distinct from a successful empty list so outages do not appear as a new account. This is the same operator/account, not a cross-customer moderation surface. Keep both routes on the shared component so feature and UX fixes stay in sync.
- CultureToons onboarding checklist guidance is renderer-aware: LTX-2.5 needs a character portrait; only legacy renderers require character registration. Keep that text consistent with `/api/culturetoons/config` and `docs/culturix-video-pipeline.md`.
- `dashboard/` — a separate internal Next.js app (trends/clusters/personas/search browsing via `lib/api.ts`). Overlaps significantly with `AdminDashboard.tsx` inside `culturix-web` — see gap #6.

**Plans** — free/pro exist as a DB field (`user_profiles.plan`), gating content-profile count and media quota. **No self-serve billing** — plan changes are admin-only via `POST /admin/users/{id}/plan`. See gap #1.

## 3. Known gaps / prioritized next steps

1. **No billing/checkout flow.** `plan` is admin-set only (no Stripe or equivalent found anywhere in the repo). This blocks real monetization — highest priority if the goal is paying users.
2. **Duplicate Twitter collectors** — `app/collectors/twitter.py` (124 lines, official API) and `twitter_apify.py` (111 lines) both exist alongside the Jina-proxy fallback in `main.py`. Confirm which is actually live, remove the dead one.
3. **Repo-root clutter** — `debug_clustering.py`, `debug_import_app_clustering.py`, `debug_run_twitter.py`, `debug_twitter_api.py`, `debug_youtube_api.py`, `drop_trends.py`, `print_personas_debug.py`, `test_trends.py` all sit at repo root alongside `scripts/` which already holds ~15 more `debug_*.py` files. Consolidate into `scripts/` or delete.
4. **Stale planning docs** — `IMPLEMENTATION.md` and `CONTENT_ENGINE_PLAN.md` (and the separate `CULTURIX_LAUNCH_BUILD_INSTRUCTIONS.md` in Cowork's outputs, if you save it here) describe designs that no longer match reality per section 2 above. Either delete them or mark them archived so future sessions don't treat them as current.
5. **Automated test coverage is incomplete.** Python tests exist under `tests/` and `scraping/tests/`, but high-value gaps remain: plan/quota enforcement in `main.py`, `content_check.py` scoring math, and collector-orchestrator error handling. No frontend test suite was found in `culturix-web/` or `dashboard/`.
6. **`dashboard/` vs `AdminDashboard.tsx` overlap** — two separate UIs both browse trends/clusters/personas. Decide whether `dashboard/` is still maintained or should be retired in favor of the in-app admin component.
7. **Two clustering paths** (`legacy_cluster.py` HDBSCAN vs `clusterer.py` Voyage+Qdrant+DeepSeek) run in the same pipeline for different purposes (admin tables vs content matching). Confirm this dual-path is intentional long-term or if `legacy_cluster.py` should be retired now that the newer path is stable.
8. **Migrations live in two places** (`/migrations` and `/supabase/migrations`) with no tooling enforcing they match — verify they're actually identical before the next schema change, or pick one and delete the other.

## 4. Notes for whoever (human or Claude Code) picks this up

- Don't re-read `IMPLEMENTATION.md`/`CONTENT_ENGINE_PLAN.md` as current-state references — they're historical/aspirational, not accurate. This file supersedes them.
- This file is regenerated periodically by a scheduled task that re-scans the repo — manual edits may be overwritten on the next scan. If you want something to persist, note it clearly or move it to a separate doc.
- Focused verification on 2026-09-29: the routed Comedy studio is in `culturix-web/src/app/admin/comedy-videos/page.tsx`; it shares the complete CultureToons producer with user mode, defaults admin to Toons for faster production, and keeps user mode's existing Characters-first setup. The local unauthenticated browser redirects to `/signup`; test the protected route while signed in as the superadmin.
- Focused admin data verification on 2026-09-29: Railway health, `/admin/trends`, and `/admin/clusters` returned HTTP 200 through `/api/admin/ping`; live Overview showed 124,248 trends, 69 clusters, 955 personas, and 9 platforms; Validation showed 500 recent records (421 approved, 79 rejected). Admin data pages now surface request failures instead of silently treating them as empty datasets; Overview labels its newest cluster list “Recent Clusters.”
- Focused public messaging update on 2026-09-29: the homepage and metadata were rewritten around the viewer-first video encyclopedia position. The remaining internal creator routes may exist, but public navigation should lead to exploration rather than account creation.
- Focused localization note on 2026-09-29: Google translation is already live for dynamic World content; the remaining work is frontend static-copy localization plus a persisted language selector for the public and signed-in user surfaces.
- Localization slice completed on 2026-09-29: `culturix-web/src/components/marketing/LanguageSwitcher.tsx` provides English/French/German/Spanish selection and persists `culturix_language`; it is mounted in `MarketingHeader` and `AppNav`, and `WorldRegionPage`/`TimeCursor` pass the selected code into the existing Google-backed digest translation. Full static-copy translation dictionaries for homepage, World UI, onboarding, dashboard, and CultureToons are still pending; do not describe the whole user app as translated until that pass is complete.
- User-shell localization slice completed after that: `LocaleProvider.tsx` now supplies the four-language static dictionary to `AppNav` and `ProductSwitcher`, covering dashboard/performance/calendar/settings/help/admin labels and product names/descriptions. Continue using this provider for page-level user UI; do not create separate per-component locale state.
- Security audit/remediation on 2026-09-29: `INTERNAL_API_SECRET` now fails closed in `app/admin_auth.py`; focused auth tests pass. OAuth initiation now goes through authenticated Next server routes, forwards the internal secret server-side, and validates `content_profile_id`/`character_brand_id` ownership before signing state. Railway and Vercel must both have `INTERNAL_API_SECRET` configured or user API/OAuth calls will correctly return 403.
- Security dependency note on 2026-09-29: frontend was upgraded from Next `14.2.5` to `14.2.35`. `npm audit --omit=dev` still reports a critical advisory whose supported automatic fix is a breaking Next 16 upgrade, plus transitive brace-expansion/d3-color/nanoid/PostCSS findings; do not run `npm audit fix --force` without a deliberate Next major-version migration and regression pass.

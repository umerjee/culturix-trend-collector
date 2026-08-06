# Culturix Studio — Architecture Document

*Written before any implementation, per the spec's own instruction. Status: proposal, not yet approved.*

## 0. The single most important finding

**~70% of this spec already exists**, under the name **CultureToons** (`app/routers/culturetoons.py`, `app/services/culturetoon_*.py`, `app/models/{character_brand,character,character_variant,expression,toon_background,toon_script,toon,toon_episode,toon_post}.py`, `culturix-web/src/components/{CharacterVariantManager,ScriptManager,ToonManager,EpisodeManager,BackgroundGallery}.tsx`). It is not a prototype — it is a live product with real users, real Kling spend, and a currently-active bug-fixing/hardening session (this same conversation) in progress.

The spec's own ground rules —

> "Reuse existing architecture wherever practical."
> "Do not create duplicate abstractions."
> "Identify the existing database models before creating new ones."

— point in one direction: **this should be built as CultureToons Phase 5+ (an extension), not a parallel "Culturix Studio" product with its own Project/Character/Episode tables next to CultureToons' CharacterBrand/Character/Toon tables.** Building a second, more elaborate character system alongside the existing one would immediately violate the spec's own anti-duplication rule, split the character roster across two products, and orphan every character/script/video a user has already created in CultureToons.

Section 2 below maps every spec entity/route/UI page to its existing CultureToons counterpart, so the "proposed architecture" in Section 3 is stated as a *diff* against real code, not a greenfield design.

The recommendation carried through the rest of this document: **extend CultureToons in place.** Where the spec's data model is genuinely richer (structured personality, relationships, memory, budget control, QA, provider abstraction), add it *to* the existing tables/services. Where the spec's model conflicts with a decision this codebase already made deliberately (see Section 6, scene-level generation), that conflict is flagged for a product decision, not silently resolved either way.

---

## 1. Existing architecture summary (verified against code, not assumed)

**Backend** — FastAPI (`app/main.py`), Postgres via SQLAlchemy (`DATABASE_URL`, Supabase-hosted), deployed on Railway (`railway.toml`, `uvicorn app.main:app`, `nixpacks.toml` adds `ffmpeg`). Most trend-engine/Shopify/billing/admin routes are still inline in `main.py`; two routers have been split out: `app/routers/clips.py` (Phase 7, unrelated/likely-dead) and `app/routers/culturetoons.py` (1600+ lines, ~45 routes, prefix `/api/culturetoons` — this is the system in scope here).

**Frontend** — Next.js (`culturix-web/`), Tailwind CSS (no component-kit layer — `lucide-react` icons + hand-written Tailwind classes per component, flat `src/components/` directory, no `components/ui/`), deployed on Vercel (`vercel.json`). Auth via `@supabase/ssr` server sessions; every `culturix-web/src/app/api/**/route.ts` is a thin proxy that resolves the Supabase session to a `user_id`, forwards to Railway with a 15-30s `AbortSignal.timeout`, and returns the JSON as-is. The backend never trusts a client-supplied `user_id` for anything but this proxy-injected value.

**Auth / tenancy** — Supabase Auth. **There is no `Workspace` concept.** Every owning entity (`CharacterBrand`, `ContentProfile`, `ShopifyStore`) is scoped directly by `user_id`, single-owner, no membership/roles table. This is a real gap against the spec's Section 3 (`Workspace.owner_id` implies multi-member workspaces) — see Section 6, decision point 1.

**Database models that exist today** (`app/models/*.py`): `character_brand`, `character`, `character_variant`, `expression`, `toon_background`, `toon_script`, `toon`, `toon_episode` (+ parts), `toon_post`, `connected_account`, plus the unrelated trend-engine models (`persona`, `cluster`, `trend*`, `content_profile`, `content_post*`, `generated_content`, `generated_media`) and Shopify models (`shopify_store`, `shopify_product`). No `workspace`, `project`, `character_relationship`, `character_memory`, `visual_style`, `culture`, `episode`/`scene` (in the spec's fine-grained sense), or `generation_usage`.

**Migrations** — no migration files for the app's own schema. Every column/table addition happens via `lifespan()`'s `ALTER TABLE IF NOT EXISTS` list in `main.py`, applied on every backend boot. New tables are created via SQLAlchemy's `Base.metadata.create_all()` at the same point (confirm exact mechanism per table before assuming — some CultureToons tables were added this way, not via raw SQL). Any new tables in this plan follow the same pattern; no separate migration tool is introduced.

**Async / jobs** — **no queue system exists.** No Celery, Redis, RQ, or Dramatiq in `requirements.txt`. All "background" work (Kling Element registration, video generation, episode stitching, publishing) runs via FastAPI's `BackgroundTasks.add_task()` — i.e. an in-process `asyncio`/thread task tied to the web server's own process. Two direct consequences, both already confirmed live this session:
- A server restart mid-generation silently orphans the job — the DB row is left in `animating` with no code path to resume it.
- The frontend has **no websocket/SSE** — every "is it done yet" UI (`ToonManager.tsx`, `CharacterVariantManager.tsx`) polls via `setInterval` + `GET` every 4-5s while status is `pending`/`animating`.

This is the single biggest infrastructure gap against the spec's Section 33 ("Video generation must NEVER block an HTTP request... use the existing queue architecture if one exists. If not, introduce a proper worker system"). See Section 5.

**Vector search** — Voyage.ai embeddings stored/searched in **Qdrant**, but only wired into the trend-engine's persona/cluster pipeline (`app/pipeline/nodes/embedder.py` → Qdrant). Nothing in CultureToons touches Qdrant today. Reusable for Section 3.5 (character memory) rather than introducing a second vector store.

**LangGraph** — `app/pipeline/graph.py` is the *only* LangGraph usage in the repo, and it is the trend-engine's own pipeline (`translate_signals → load_signals → embed_signals → cluster_and_persist → cluster_trends → validate_clusters → map_trend_history → map_persona_tags → map_personas → generate_content → validate_ideas → write_digests`). CultureToons does **not** use LangGraph anywhere — script/video generation there is a direct FastAPI route calling a service function calling a provider, no graph orchestration. The spec's Section 17 (18-node LangGraph production graph) would be new infrastructure, not a reuse of the existing graph (different domain, different trigger model — the existing graph runs on a schedule over trend signals, not on-demand per episode).

**AI provider abstractions that exist today, per capability:**

| Capability | File | Notes |
|---|---|---|
| Image generation | `app/media/image_hybrid.py` `HybridImageProvider` | Cloudflare FLUX.1 schnell (free) → Qwen-Image (paid) fallback. Used by every character/variant/background image route. |
| Video (image-to-video) | `app/media/video.py` `KlingProvider` | Shopify reels only. AK/SK JWT auth. |
| Video (multi-shot, character-consistent) | `app/media/kling_omni.py` `KlingOmniProvider` | CultureToons only. **Deliberately separate** from the above — different API surface entirely, static-API-key auth (migrated off AK/SK this session after a live 401). `generate_omni_video()`, `create_element()`, `create_voice()` all live here. This is the closest existing thing to the spec's `VideoProvider` protocol, but it is a concrete class, not an interface — no second video provider has ever been plugged in. |
| Voice | `app/media/elevenlabs_voice.py` `ElevenLabsProvider` | Optional CultureToons dubbing fallback; Kling's own native audio is the default (a settings flag inside `kling_omni.py`, not a separate provider class). `EdgeTTSProvider` also exists but serves the *trend engine's* Phase-7 clip pipeline, unrelated. |
| Text/LLM | inline per-service | Qwen-max primary / Claude Haiku fallback, duplicated (by design, per this codebase's stated convention — "small-helper duplication over cross-module coupling") across `content_strategist.py`, `shopify/content_ideas.py`, `culturetoon_script.py`. No shared `LLMProvider` abstraction. |
| Publishing | `app/social/{youtube,tiktok,instagram,twitter}.py` | Real `OAuthProvider` ABC, already used by both the trend engine and CultureToons via `ConnectedAccount.character_brand_id`. This is a working example of the abstraction pattern the spec asks for elsewhere. |

**Storage** — Supabase Storage (`app/media/storage.py`, bucket `media`, public-read), one flat `upload(bytes, path, content_type) -> url` function, no lifecycle states, no separate `Asset` table — every model just stores a raw `*_url` string column (`base_image_url`, `image_url`, `raw_video_url`, etc.). This is a real gap against Section 8/34 (`character_assets`/`Asset` as a first-class versioned entity) — see Section 3.3.

**Design system** — Tailwind utility classes directly, `lucide-react` icons, no dark/light mode toggle observed in CultureToons screens (unclear if the wider app has one — not verified for this doc). Every CultureToons screen already follows Section 36's stated preference (cards, status badges, inline forms, no exposed raw prompts) — this is not new ground to break.

**Cost/budget control** — **does not exist.** Confirmed gap, documented in this repo's own `CLAUDE.md`: CultureToons' Kling Omni generation, Element registration, and ElevenLabs dubbing all run with zero plan/quota gate, unlike the original trend-engine media path (`/api/generate-media`, pro-capped 50/month). No `generation_usage`-equivalent table exists anywhere in the app. This is the spec's Section 28 in full — genuinely new work, and arguably the single highest-value item in this whole spec given it's a live financial exposure today.

---

## 2. Spec-to-existing-code mapping

| Spec entity/section | Existing equivalent | Gap |
|---|---|---|
| `Workspace` | — (no multi-tenant workspace; `user_id` is the tenancy boundary) | New, or explicitly deferred — see decision point 1 |
| `Project` | `CharacterBrand` (a "toon account," e.g. "Funny Clips") | Rename/repurpose, don't duplicate |
| `characters` | `Character` + `CharacterVariant` (two-level: base character → cultural variant) | Spec's single flat `characters` table doesn't distinguish base-vs-variant; CultureToons' split is *more* structured for this exact product (culturally-varied recastings of one role), keep it |
| Structured personality (§5) | — (personality lives only as `Character.description` free text) | New: add structured `personality` JSON column |
| `character_relationships` | — | New table, straightforward addition |
| `character_memories` | — (no memory concept; scripts don't reference prior episodes) | New table + Qdrant wiring |
| `character_assets` | — (single `*_url` columns, no asset history/versioning) | Partial new: could stay minimal (see 3.3) rather than full asset-table rebuild |
| `voice_profiles` | `CharacterVariant.voice_provider` / `.elevenlabs_voice_id` fields directly on the variant | Spec wants a separate table; current inline-fields approach works fine for 1 voice per variant — only worth splitting out if multi-voice-per-character becomes real |
| `visual_styles` | `ART_STYLES` — a fixed Python dict of 5 styles (`cartoon_3d`, `anime`, `flat_vector`, `claymation`, `cinematic_cultural` — the last added this session), shared globally, not per-project | Gap: not a DB entity, not customizable, not project-scoped. Real work if per-project custom styles are wanted |
| `cultures` | `CharacterVariant.culture_tag` — a free-text string (e.g. "Chinese", "African") | Gap: no structured culture library, no stereotype-avoidance guidance stored anywhere. This is actually a *quality* gap already visible in this session's own testing (ethnicity rendering inconsistency) |
| `episodes` | `Toon` (single-video) + `ToonEpisode` (multi-part story chaining several `Toon`s) | See Section 6 — CultureToons' unit of production is one `Toon` = one video, not a decomposed scene list |
| `episode_characters` | `ToonScript.character_variant_ids` (array on the script, not a join table) | Functionally equivalent, different shape |
| `scenes` / `scene_characters` | `ToonScript.shots` — a JSON list of `{shot_number, duration_seconds, action, expression, dialogue, speaker_variant_id}`, compiled into **one** Kling Omni multi-shot prompt, generated as **one** video | Major divergence — see Section 6 |
| `VideoProvider` protocol | `KlingOmniProvider` (concrete class) | New: extract the protocol, keep Kling as the only implementation for now |
| `VoiceProvider` protocol | `ElevenLabsProvider` + Kling's native-audio flag | New: same treatment |
| LangGraph production graph (§17) | `app/pipeline/graph.py` (trend engine only, unrelated domain) | Decided against — see Section 6, decision 4 |
| Prompt builder (§18-19) | `culturetoon_script.py::build_kling_prompt()` (already assembles shot data into Kling's DSL) + `_build_cartoon_prompt()`/`_build_background_prompt()` in `culturetoons.py` | Exists, less structured than spec's template — worth tightening, not replacing |
| `/studio` nav + pages | `/dashboard/culturetoons` + `CultureToonApp.tsx`'s tab bar (Characters/Backgrounds/Scripts/Toons/Episodes) | Rename/restructure existing nav, don't build a second one |
| Production queue UI (§27) | — (no queue = no queue UI; status is per-card polling) | New once a real queue exists |
| Cost control (§28) | — | New, high priority (see §1) |
| QA (§29) | — (no scoring of any kind on generated content) | New |
| Publishing (§30) | `app/social/*`, `ConnectedAccount`, `POST /api/culturetoons/toons/{id}/publish`, `ToonPost` | **Already built and live** — reuse directly, do not re-abstract |
| Analytics feedback (§31) | `ToonPost` tracks views/likes/comments/shares (`fetch_toon_and_record`), but nothing reads it back into idea generation | Partial — ingestion exists, the *feedback loop* into generation doesn't |
| `generation_usage` (§28) | — | New |

---

## 3. Proposed architecture (additive to CultureToons)

### 3.1 Naming decision

Rename in the UI/product-facing copy only (not necessarily the DB table names, to avoid a disruptive migration): `CharacterBrand` → presented as "Project" where the spec's language is used; `Toon` stays `Toon` (renaming a live, tested, actively-developed table today is not worth the churn this session alone demonstrates the pace of iteration on). New tables use the spec's naming (`character_relationships`, `character_memories`, `generation_usage`) since these don't exist yet and the spec's names are fine.

### 3.2 Structured personality (spec §5)

Add to `Character`:
```
personality = Column(JSONB, nullable=True)
```
Shape: `{"traits": {trait_name: float 0-1, ...}, "behavioral_rules": [str, ...], "speech_rules": [str, ...]}`, validated at the API boundary (Pydantic model), not DB-constrained (JSONB, same pattern as `ToonScript.shots`). `Character.description` stays as the free-text summary shown in card UIs; `personality` becomes the structured source the prompt builder reads from. No new table.

### 3.3 Character assets — minimal version, not the full spec table

The spec's `character_assets` table (versioned, provider-tagged, typed per asset kind) is more machinery than the current product needs. **Recommendation: don't build it yet.** Today's `Character.base_image_url`/`reference_image_url` and `CharacterVariant.image_url`/`reference_image_url` already cover "current canonical portrait" — the actual gap is **no history when an image is regenerated** (confirmed this session: regenerating a character portrait silently discards the old one, no different from the video-regeneration-history bug already fixed for `Toon` this session). The minimal fix that solves the *actual* pain point without the full asset-table rebuild:
```
Character.previous_image_urls = Column(ARRAY(Text), nullable=True)
CharacterVariant.previous_image_urls = Column(ARRAY(Text), nullable=True)
```
— same pattern as `Toon.previous_video_urls`, shipped this session. Expression sheets/pose sheets/turnarounds (the richer asset types in §8) stay out of scope until there's a concrete generation flow that needs them; `Expression` already exists as its own table for the one asset type CultureToons currently generates beyond the main portrait.

### 3.4 Relationships (spec §6) — DECIDED: character-level

```
character_relationships:
  id, brand_id (not project_id — matches existing tenancy),
  character_a_id, character_b_id,  # keyed on Character, not CharacterVariant
  relationship_type, description, emotional_dynamic,
  conflict_level, trust_level, humor_dynamic,
  behavioral_rules (ARRAY(Text)),
  created_at, updated_at
```
Confirmed with the user: character-level, matching the spec as literally written. One relationship per pair of base Characters, shared across all their variants (e.g. "Kumar and Hans" applies whichever cultural variant of Kumar is cast). Simpler model, no per-variant relationship proliferation. `RelationshipResolver` (prompt-building step) looks up by the pair of `Character.id`s present in a script's cast, resolved from each cast `CharacterVariant.character_id`.

### 3.5 Character memory (spec §7)

New table:
```
character_memories:
  id, character_variant_id, brand_id,
  memory_type (backstory|recurring_fact|relationship_event|previous_joke|preference|running_gag|episode_event),
  content (Text), importance (Int),
  source_toon_id (nullable FK to toons, not "episode" — see §6),
  embedding (reuse Qdrant, not a new pgvector column — Voyage.ai + Qdrant already exists and is already the pattern for semantic retrieval in this codebase)
  created_at
```
Retrieval: a new `culturetoon_memory.py` service, `retrieve_relevant_memories(character_variant_ids, episode_context) -> list[str]`, embeds the context text via the existing Voyage client and queries a new Qdrant collection (`culturetoon_memories`, separate from the trend engine's collection). Memory *creation* is the harder design question — does every published `Toon` get summarized into a memory automatically (LLM call after publish), or is it manual/curated? Recommend starting manual (a simple "Add memory" form on the character page) and only automating extraction once there's evidence users want it — matches the spec's own §42 ("do not over-engineer before proving the production loop").

### 3.6 Visual styles as a real entity (spec §10)

Today `ART_STYLES` is a hardcoded Python dict shared by every brand. Making it a true per-project entity means a new table:
```
visual_styles: id, brand_id, name, description, art_direction, lighting,
  camera_style, character_style, environment_style, animation_style,
  color_direction, negative_prompt, generation_rules (JSONB), version, is_default
```
with `Character.visual_style_id` and `ToonBackground` generation reading from it instead of the fixed dict. **Recommend deferring this** unless a concrete user need for *custom* (not just a 5th preset) styles shows up — the dict-based approach just proved itself extensible this session (adding "Cinematic cultural" took one dict entry, no migration). Converting to a full entity is a bigger lift than the current evidence justifies; revisit if/when a user wants brand-specific style tuning beyond picking from a preset list.

### 3.7 Culture library (spec §11)

New table, genuinely useful given this session's own findings (ethnicity rendering inconsistency, background cultural-accuracy issues):
```
cultures: id, name, country, region, language,
  cultural_patterns (JSONB), humor_sensitivity, common_misunderstandings (ARRAY(Text)),
  stereotypes_to_avoid (ARRAY(Text)), positive_traits (ARRAY(Text)), metadata (JSONB)
```
`CharacterVariant.culture_tag` (currently free text like "Chinese", "African") becomes a nullable FK to `cultures.id`, falling back to the free-text field for cultures not yet in the library (don't force every user through a curated list before they can create a variant — this table should *inform* prompt construction, not gate character creation). This directly addresses two real bugs already surfaced this session (weak ethnicity anchoring, "empty"/inaccurate cultural backgrounds) by giving the prompt builder structured cultural detail to draw on instead of a bare tag string.

### 3.8 Provider protocols (spec §9, §16, §30)

Extract protocols now that there's a second real use case to design against (this document). `app/media/protocols.py` (new file):
```python
class VideoProvider(Protocol):
    async def generate_scene(self, scene, characters, style, references, options) -> VideoGenerationResult: ...

class VoiceProvider(Protocol):
    async def generate_dialogue(self, dialogue: list, voice_profiles: list, options: dict) -> AudioResult: ...
```
`KlingOmniProvider` and `ElevenLabsProvider` get adapted to implement these (thin wrapper methods, not rewrites — their existing public methods already do this work, e.g. `generate_omni_video` becomes the concrete `generate_scene` for Kling). No second implementation is built now; the value is making the *call site* (the video-generation service) depend on the protocol, not the concrete class, so a future Runway/Veo provider is a plug-in, not a rewrite.

### 3.9 Cost control (spec §28) — highest priority new work

```
generation_usage: id, user_id, brand_id, toon_id (nullable),
  provider, model, generation_type, input_units, output_units,
  credits, estimated_cost, actual_cost, created_at
```
(No `scene_id` — scene-level generation was decided against, Section 6 decision 2; every generation is scoped to a `toon_id` or is toon-independent, e.g. a character portrait.)
Every call into `KlingOmniProvider`, `HybridImageProvider`, `ElevenLabsProvider` gets wrapped to record one row. Budget enforcement (`character_brand.daily_budget`/`monthly_budget`/warning/hard-stop, mirroring the spec's example) reads a rolling sum from this table before allowing a new generation to start — same enforcement point as the existing but-unused `app/billing.py`/`app/media/quota.py` pattern (pro-cap 50/month) already used elsewhere in this app, just applied to CultureToons for the first time. This is not new architecture, it's applying an existing pattern to a subsystem that was never wired into it.

### 3.10 QA (spec §29) — DECIDED: full scope now, technical first then AI judge close behind

New `culturetoon_qa.py` service, called after generation succeeds, before a `Toon` is eligible to publish. Confirmed with the user: build the full spec'd scope, not just the deterministic subset — the cultural-safety signal in particular is valuable from day one, not something to wait on. Two passes, landed as two back-to-back PRs (not gated on a waiting period, just split for reviewability):

1. **Technical + visual (deterministic, no LLM call)**: duration matches request, aspect ratio correct, file not corrupt/zero-byte, audio track present if expected. Cheap, this session already proved the exact checks needed (the duration/audio probing done live via `pyav` this conversation is precisely this check, just manual).
2. **AI judge (LLM call per generation)**: comedy score, cultural-safety score (stereotype risk, demeaning-portrayal risk, using `cultures.stereotypes_to_avoid` from §3.7 as grounding context, not a bare vibe check), story/pacing score. Returns the spec's `{visual_score, comedy_score, cultural_score, technical_score, overall_score, publish_recommended}` shape. Same Qwen-max primary / Claude Haiku fallback pattern as every other LLM call in this codebase — no new provider.

`Toon.status` gains a checkpoint: generation success moves a toon to a new `qa` status (between `ready` and `posted` in the existing idea→animating→ready→posted→archived→failed flow — insert `qa` after `ready`), QA results stored as JSONB on the toon, and `publish_recommended: false` blocks the publish button in the UI (soft block — a low cultural_score should stop and show why, not silently prevent publishing with no explanation) but doesn't hard-delete or auto-archive; a human always makes the final call.

### 3.11 Analytics feedback loop (spec §31)

`ToonPost` already has the raw metrics. New work is entirely in *using* them: a scheduled job (same `app/scheduler.py` pattern already running trend-engine crons — do **not** create a new Railway Cron Service, per this repo's own standing instruction) that aggregates `ToonPost` performance by `(character_variant_ids, culture_tag, tone, duration_bucket)` and feeds a summary into the script-suggestion prompt (`culturetoon_script.py`) as additional context, the same way trend/persona context is already injected there. No new table needed beyond an optional materialized summary if the raw aggregation query gets expensive.

---

## 4. Frontend routes (extends, does not replace, `/dashboard/culturetoons`)

The spec's `/studio/*` tree maps onto the existing `CultureToonApp.tsx` tab bar (Characters / Backgrounds / Scripts / Toons / Episodes) plus new tabs for what's new:

```
/dashboard/culturetoons
  (Characters tab — existing, gets Relationships + Memory sub-sections)
  (Backgrounds tab — existing)
  (Scripts tab — existing)
  (Toons tab — existing, no rename; one-shot generation was kept, see Section 6 decision 2)
  (Episodes tab — existing ToonEpisode multi-part chaining)
  + Production (new — deferred alongside the queue/worker backlog item, §5/decision 3; a meaningful queue-status view needs the reconciliation work first)
  + Usage & Budget (new — surfaces generation_usage + budget controls, ships with Phase 1/2)
```
Recommend **not** introducing a `/studio` URL prefix or a second top-level nav item — `CultureToons` is already the `ProductSwitcher` entry for this exact product surface; a second entry point for the same underlying data would recreate the confusion the spec explicitly warns against ("Do not build fake UI that is not backed by the data model").

## 5. Worker/queue requirements

This is the largest true infrastructure gap, and per Section 6 decision 3, **neither option below is being built as part of this roadmap** — both are parked as a pre-launch hardening backlog item, picked up once the product is otherwise ready to go live:

- **Minimal path** (the one to reach for first, when this backlog item is picked up): keep `BackgroundTasks`, fix the actual failure mode (orphaned jobs on restart) by adding a startup reconciliation pass — on boot, any `Toon`/`Character`/`CharacterVariant` left in `animating`/`pending` with no completion in N minutes gets marked `failed` with a clear "interrupted by a restart" error, so at least the UI stops lying. Cheap, ships in an afternoon, doesn't add infra.
- **Real path**: introduce Redis + RQ (lighter than Celery, matches this codebase's stated preference for boring/small dependencies) as an actual job queue, with a separate worker process on Railway. Required only if true horizontal scaling or job resumption-after-restart becomes a measured need, not a hypothetical one. Non-trivial: new Railway service, new deploy config, new local-dev story.

## 6. Decisions (resolved with the user before any implementation)

**1. Workspace/multi-tenancy — SKIP.** The spec assumes multi-member workspaces (`owner_id` implies non-owner members exist). The current app has none — every product surface is single-owner-per-`user_id`. Building real multi-user workspaces is a cross-cutting change touching auth, every ownership check in `culturetoons.py`, and billing — far bigger than anything else in this document. **Confirmed: skip Workspace entirely, keep `CharacterBrand`/`user_id` as the tenancy boundary**, revisit only if a concrete multi-user need shows up.

**2. Scene-level generation vs. one-shot multi-shot generation — KEEP ONE-SHOT.** This was the sharpest conflict in the spec. Sections 14/15/26 wanted scenes as independently generatable, independently regeneratable, ffmpeg-assembled units. **Confirmed: not building this.** CultureToons keeps trusting one Kling Omni multi-shot call per episode as a single coherent video — the decision this session already shipped (removing candidate-clip cutting) stands. "Regenerate" means regenerate the whole short clip, not an individual scene within it. This avoids N-times the Kling cost per episode and avoids unproven cross-clip character-consistency risk from stitching separately-generated clips. Sections 14/15/26/33's ffmpeg-assembly machinery is **not built**.

**3. Worker/queue investment — DEFERRED to pre-launch hardening, not an active phase.** No queue system exists today (`BackgroundTasks` only); a restart mid-generation silently orphans jobs, confirmed live this session. **Confirmed: not building the reconciliation fix (or a real queue) as part of this roadmap now** — tracked as a pre-launch hardening item to pick up once the product is otherwise ready to go live (see Section 7's backlog note). Do not treat this as "resolved," just deliberately sequenced last.

**4. LangGraph for the production pipeline — DON'T ADOPT (default, unopposed).** The spec wanted an 18-node graph. The existing LangGraph usage (`app/pipeline/graph.py`) is a scheduled batch job over trend signals — different domain, different trigger model, not something this extends. The user didn't raise an objection to the recommendation, so this proceeds as: keep the existing pattern (a service function per stage, called sequentially from a route/background task), the same pattern CultureToons' script→video pipeline already uses successfully. Revisit only if a concrete need for graph-level branching/retry/checkpointing shows up.

**5. Relationship keyed on Character vs. CharacterVariant — CHARACTER-LEVEL.** See Section 3.4. Confirmed: one relationship per pair of base `Character`s, not per `CharacterVariant` pair.

**6. QA scope — FULL SCOPE NOW.** See Section 3.10. Confirmed: build technical/visual deterministic checks *and* the AI-judge comedy/cultural/story scoring together (as two back-to-back PRs, not gated on a waiting period) rather than deferring the AI-judge half. The cultural-safety signal is treated as valuable from day one.

**7. Personality → prompt determinism (note, not a fork).** Spec §18 wants character identity "deterministic" from structured data, not LLM-rewritten per call. Already broadly true for *visual* identity (Kling Elements registered once, reused) but not yet true for *behavioral* identity — script generation is a fresh LLM call per script with no persistent personality object constraining it today. `Character.personality` (§3.2) only pays off once the script-generation prompt is rewritten to actually consume it — real prompt-template work, tracked explicitly in Phase 3, not assumed to fall out of the schema change alone.

## 7. Implementation phases (final — reflects all resolved decisions in Section 6)

**All phases below are EXECUTED**, each landed as its own commit and covered by tests. Where implementation deviated from this document's original sketch, the deviation is called out explicitly rather than silently reconciled — the doc is being kept honest against the code, not edited to look like it predicted everything.

**Phase 1 — Foundation — DONE.** `Character.personality` (JSON, `app/models/character.py`), `character_relationships` table (`app/models/character_relationship.py`, character-level per decision 5), `generation_usage` table (`app/models/generation_usage.py`) + recording wired into all three providers via `app/services/culturetoon_usage.py::record_usage()`. Also folded in while touching this code: `Character.previous_image_urls`/`CharacterVariant.previous_image_urls` (§3.3's minimal version — portrait regeneration no longer discards history).

**Phase 2 — Budget enforcement — DONE.** `CharacterBrand.daily_budget`/`monthly_budget`, `check_budget()` gating every generation route (`_check_budget_or_raise` in `app/routers/culturetoons.py`) before any provider is called — 402 at 100% spend, non-blocking warning from 80%. `UsageBudgetPanel.tsx` + a new "Usage & Budget" tab.

**Phase 3 — Relationships + personality, wired into generation — DONE.** `RelationshipManager.tsx` (simple list, no graph) and a personality editor (trait sliders + behavioral/speech rule lists) on the Characters tab. `culturetoon_script.py`'s prompt builder (`_cast_line`, `_personality_line`, `_relationship_context`) now actually consumes `Character.personality` and relationship context whenever 2+ characters are cast together, via a shared `_gather_script_generation_context()` helper used by all three script-suggestion routes.

**Phase 4 — Character memory — DONE.** `character_memories` table (`app/models/character_memory.py`, variant-level), `MemoryManager.tsx` (manual add/list/delete), retrieval via `app/services/culturetoon_memory.py` — reuses the existing Voyage.ai client (`app/embeddings.py`) and Qdrant instance in a new `culturetoon_memories` collection, fully fail-open (a Qdrant/Voyage outage returns no memories, never blocks script generation). **Caught during implementation, not anticipated in the original doc**: this retrieval path makes a real network call (and, once memories exist, a real billed Voyage embedding call) whenever `QDRANT_URL`/`VOYAGE_API_KEY` are set — which they are in this environment via `.env`. Every test touching script suggestion now explicitly mocks `retrieve_relevant_memories` (autouse fixture in `tests/test_culturetoons.py`); `tests/test_culturetoon_memory.py` covers the real logic with the `QdrantClient` class itself mocked, never hitting the network.

**Phase 5 — Culture library — DONE.** `cultures` table (`app/models/culture.py`, global/shared, not brand-scoped), seeded on boot with Indian/Chinese/African (this account's actual roster) via an idempotent seed block in `main.py`'s `lifespan()`. `CharacterVariant.culture_id` links to it, falling back to the existing free-text `culture_tag`. Wired into script generation (`_culture_context()` in `culturetoon_script.py`) surfacing `humor_sensitivity`/`common_misunderstandings`/`positive_traits` as material alongside an explicit `stereotypes_to_avoid` guardrail. **Scope trimmed from the original sketch**: image/background prompt wiring was deferred — the frontend culture-picker dropdown was also deferred (`culture_id` is settable via the API today, no dedicated UI yet) — given four more phases remained; the script-generation wiring was judged the highest-value piece and is complete.

**Phase 6 — Provider protocols — DONE.** `app/media/protocols.py`: `VideoProvider`/`VoiceProvider` as `@runtime_checkable` Protocols, **synchronous** (not `async def` as originally sketched — no code in this repo uses async providers, so `async` would have been an invented convention, not a reused one). `KlingOmniProvider.generate_scene()` and `ElevenLabsProvider.generate_dialogue()` are thin adapters satisfying them. **Deliberately not wired into `app/services/culturetoon_video.py`'s actual call sites** — those still call `generate_omni_video()`/`synthesize()` directly. Migrating a working, tested pipeline to route through a protocol with exactly one implementation would add a layer with no present payoff; the seam exists for when a second provider is actually being integrated, not before.

**Phase 7 (a+b combined) — QA — DONE.** Built as one service (`app/services/culturetoon_qa.py`) rather than two sequential PRs — the technical (7a) and AI-judge (7b) halves share one result shape and one call site, so splitting them across two merges would have meant a real intermediate state nobody wanted to ship. `run_technical_qa()` reuses `ffmpeg-python`'s `probe()` (same dependency `culturetoon_clip_cutter.py` already uses — no new dependency, and notably NOT `pyav`/`av`, which was used ad-hoc for manual diagnosis earlier in this session but was never a declared project dependency). `run_ai_judge_qa()` scores comedy/cultural via the usual Qwen-max/Haiku pattern, grounded in Phase 5's `stereotypes_to_avoid`. **Deviation from the original sketch, made deliberately**: no new `"qa"` value was inserted into `Toon.status` (`idea|animating|ready|posted|archived|failed` is untouched) — QA runs automatically right after generation and lands as `Toon.qa_results`/`Toon.publish_recommended` metadata instead. Inserting a new status would have meant auditing every existing status check across the frontend and backend for a cosmetic state-machine change with no functional need; the softer metadata-only approach gives the same UI signal (a warning banner in `ToonManager.tsx` before publishing) without that blast radius. `publish_recommended` is never a hard server-side block — a human always makes the final call, per the doc's own original intent.

**Phase 8 — Analytics feedback loop — DONE.** `app/services/culturetoon_analytics.py::get_cast_performance_context()`, injected into all three script-generation routes via `_gather_script_generation_context()`. **Deviation from the original sketch**: computed live at generation time (one small join per brand: `ToonPost` → `Toon` → `ToonScript`, filtered to `status='tracked'`), not via a scheduled aggregation job. A scheduled pre-aggregation + cache would solve a performance problem that doesn't exist at current volume, at the real cost of staleness and scheduler complexity — revisit only if live computation is ever a measured bottleneck, not before.

**Not on the active roadmap (unchanged from decisions in §6):**
- **Scene-level generation / ffmpeg assembly** — decided against (decision 2).
- **Real Workspace/multi-tenancy** — decided against for now (decision 1).
- **LangGraph production pipeline** — decided against (decision 4).
- **Worker/queue hardening** (startup reconciliation pass, or a real Redis/RQ queue) — still a pre-launch hardening backlog item per decision 3, not built.
- **Culture-picker frontend UI, image/background culture-context wiring** — deferred from Phase 5, see above.

Every phase's tests live alongside the code that changed: `tests/test_culturetoon_usage.py`, `tests/test_culturetoon_memory.py`, `tests/test_culturetoon_qa.py`, `tests/test_culturetoon_analytics.py`, `tests/test_elevenlabs_voice.py` are new files; `tests/test_culturetoons.py`, `tests/test_culturetoon_script.py`, `tests/test_culturetoon_video.py`, `tests/test_kling_omni.py` gained new test classes. The full repo suite (631+ tests as of this writing) passes.

---

## 8. What this document deliberately does not do

It does not propose a `Workspace`/`Project` rebuild, a second character system, a new LangGraph pipeline, a full asset-versioning table, or scene-level generation — each of those is either already covered by existing CultureToons infrastructure, or flagged above as needing an explicit user decision before any code gets written, per the spec's own instruction not to begin large-scale implementation yet.

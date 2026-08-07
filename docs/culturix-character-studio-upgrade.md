# Character-Based Posting → Persistent Cartoon Studio — Upgrade Plan

*Written before further implementation, per this spec's own instruction. Status: inspection complete, Phase 1 ready to implement, one direct conflict flagged below needs your decision before anything past Phase 1 proceeds.*

## 0. Headline finding: most of this already shipped

This spec describes CultureToons roughly as it existed *before* the previous two sessions in this conversation. Nearly everything in sections "CHARACTERS" through "COST CONTROL" is already built, tested, and live in production as of the last deploy (`fdf70f9`). This doc is a precise gap analysis against the **current** schema (verified by reading the actual model files, not assumed), not a restatement of the spec as if starting fresh.

The one place this spec asks for something **already explicitly decided against**, in this same conversation: fine-grained Scene-level generation (see §5 below). That needs your re-confirmation before any Episode/Scene work starts — I have not silently reopened it.

## 1. What's already built (verified against current code)

| Spec ask | Status | Where |
|---|---|---|
| Personality sliders (confidence, humor, patience, competitiveness, warmth, risk tolerance, formality, impulsiveness) | **DONE** | `Character.personality` JSON, `CharacterVariantManager.tsx`'s Personality section, `PERSONALITY_TRAITS` in `culturix-web/src/lib/types.ts` |
| Behavioral rules ("Behavioral DNA") | **DONE**, injected into generation | `Character.personality.behavioral_rules`, consumed by `culturetoon_script.py::_personality_line()` |
| Speech rules | **DONE** | `Character.personality.speech_rules`, same injection path |
| Cultural variants | **DONE** (predates this upgrade) | `CharacterVariant` — one base `Character`, many culturally-varied castings |
| Related Characters (separate persistent characters, e.g. Kumar→Priya/Raj/Hans) | **DONE**, functionally — not reframed in the UI under that name yet | `CharacterRelationship` already links two independent `Character` rows (not variants of one character) — this *is* "Related Characters," it just isn't labeled that way in the UI. See Phase 1 below. |
| Relationships (trust, conflict, humor dynamic, description, behavioral rules, injected into generation) | **DONE**, with one field gap | `CharacterRelationship` has `trust_level`, `conflict_level`, `humor_dynamic`, `description`, `behavioral_rules`, `relationship_type`, `emotional_dynamic` — **no separate `affection` field** (folded into `emotional_dynamic`/`description` today), **no relationship history/event log** (a timeline of what happened between two characters over time — different from `character_memories`, which is per-character not per-pair). Gap, see §4. |
| Memory (backstory, preference, running joke, previous episode, relationship event, recurring behavior) | **DONE**, categories close but not identical | `CharacterMemory.memory_type`: `backstory\|recurring_fact\|relationship_event\|previous_joke\|preference\|running_gag\|episode_event` — covers the spec's 6 categories (naming differs slightly: `running_gag`≈"running joke", `episode_event`≈"previous episode", no distinct "recurring behavior" separate from `recurring_fact`). Retrieved via Qdrant semantic search, injected into script generation. `source_toon_id` links a memory to the `Toon` it came from (spec wants "originating episode" — see §5, no fine-grained Episode/Scene distinction exists yet to link to). |
| Voice persistence | **DONE**, not as a separate table | `CharacterVariant.voice_provider`/`.kling_voice_id`/`.elevenlabs_voice_id` — persists per variant. Spec's original ask (`voice_profiles` as its own table) was deliberately simplified to inline fields in the first pass of this work, since one voice per variant covers every case seen so far. Revisit only if multi-voice-per-character becomes a real need. |
| VideoProvider/VoiceProvider abstraction, Kling as first implementation | **DONE** | `app/media/protocols.py` — `@runtime_checkable` Protocols, `KlingOmniProvider.generate_scene()`/`ElevenLabsProvider.generate_dialogue()` as adapters. Existing call sites in `culturetoon_video.py` deliberately still call the concrete methods directly (documented reasoning: no second provider yet to justify the migration). |
| Cost tracking (provider, model, credits, estimated/actual cost) | **DONE**, missing episode/scene/attempts | `GenerationUsage`: `provider`, `model`, `generation_type`, `input_units`/`output_units`, `cost_usd`, `toon_id`. **No `episode_id`, no `scene_id` (no Scene entity exists), no `attempts` counter** — see §5/§4. |
| Budget enforcement, never autonomous-unbounded | **DONE** | `CharacterBrand.daily_budget`/`monthly_budget`, `check_budget()` gates every generation route, 402 at 100%, warning from 80% |
| QA before Toon is publish-ready | **DONE** | `app/services/culturetoon_qa.py` — technical/visual deterministic checks + AI-judge comedy/cultural scoring, `Toon.qa_results`/`.publish_recommended` |
| Analytics feeding back into generation | **DONE**, live-computed not scheduled | `app/services/culturetoon_analytics.py::get_cast_performance_context()`, injected into script prompts |
| Usage & Budget nav tab | **DONE** | `CultureToonWorkspace.tsx`'s tab bar already has it |
| "Relationships" as its own nav tab | **NOT DONE** — currently a sub-section on the Characters tab, not a top-level tab | See §4 |

## 2. What's genuinely new in this spec vs. the prior work

1. **Personality Summary** — an auto-generated one-paragraph text ("Kumar is confident, warm and highly persuasive...") derived from the trait sliders, shown on the character card. New.
2. **"Relationships" promoted to a top-level nav tab**, separate from the Characters page (currently nested inside `CharacterVariantManager.tsx`). New, small.
3. **"Variants & Related Characters" reframing** — explicitly separating "same character, different context" (existing `CharacterVariant`) from "different character, connected by relationship" (existing `CharacterRelationship`, but not surfaced this way in the UI). Mostly a UI/labeling change over already-existing data — no new backend entities needed, this is just making an existing distinction legible to the user instead of implicit.
4. **Locations** (Backgrounds evolved) — country, canonical reference images (plural — currently `ToonBackground` has exactly one `image_url`), rooms/views, reusable across episodes with persistent references. Real gap — current `ToonBackground` is a single flat image with no room/view breakdown and no "canonical set" concept.
5. **Relationship `affection` field + relationship history/event log.** Real gap, see §1.
6. **Episode → Scene fine-grained architecture**, independently regeneratable scenes. **This is the direct conflict — see §3.**
7. **`attempts` counter and `episode_id`/`scene_id` on generation_usage.** Depends on #6 being resolved first.

## 3. The direct conflict — needs your explicit decision before any Episode/Scene work

Two conversation turns ago, in this same session, you were asked directly:

> *"Sections 14/15/26 want each scene independently generated and regenerated... Which direction for the actual production model?"*

And you chose **"Keep one-shot generation (Recommended)"** — explicitly: no ffmpeg scene assembly, no per-scene independent generation, `ToonEpisode` stitches whole `Toon`s ("parts"), not fine-grained scenes. That decision is recorded in `docs/culturix-comedy-architecture.md` §6, decision 2, and is what's actually live in production right now.

This new spec asks for exactly the thing that was decided against:

> *"Every episode should be broken into short scenes... Each scene must be independently regeneratable. If Scene 3 fails, do NOT regenerate the whole episode."*

I am not silently reversing that decision either direction. Before I touch Episodes/Scenes (this spec's Phase 5, and the `scene_id`/`attempts` fields in Phase cost-tracking), I need to know: **has your view genuinely changed since that decision**, or did this spec get drafted without that context? The cost/consistency tradeoff is the same one already discussed — true per-scene generation means N separate Kling calls per episode instead of 1, and unproven cross-scene character-consistency versus Kling Omni's own multi-shot handling. If you do want to reopen it, I'll implement it for real; if not, I'll keep `ToonEpisode`'s existing part-based model and treat "Scenes" in this spec as already satisfied by `ToonScript.shots` (which already are individually described, just not independently *generated*).

## 4. Implementation order (adapted from the spec's 12 phases, reconciled against what's already done)

**Phase 1 — Character persistence UI/labeling improvements (implementing now, this turn).**
- Personality Summary: auto-generated text from `Character.personality.traits`, shown on the character card. Small LLM call (same Qwen/Haiku pattern) or a cheap template-based sentence — template first, since this doesn't need creative writing, just accurate reporting of the sliders already set.
- "Variants & Related Characters" section reframing on the Characters tab: split the existing cultural-variants UI and the existing relationships UI into clearly labeled sub-sections under that heading, so the distinction the spec wants is visible, not just structurally true.
- Promote Relationships to its own top-level nav tab (currently nested).
- Add `affection_level` (0-10, same shape as `conflict_level`/`trust_level`) to `CharacterRelationship`.

**Phase 2 — Relationship history (event log).** New `character_relationship_events` table (or reuse `character_memories` with a `relationship_id` — decide during implementation which is the better fit) so "what happened between Kumar and Hans over time" is queryable, not just the static current-state relationship row.

**Phase 3 — Locations (Backgrounds evolution).** `ToonBackground` gains `country`, `visual_style`, and a real one-to-many for canonical reference images (a background can have 2-3 canonical angles/rooms, not just one flat image) — likely a small new `location_reference_images` table rather than overloading `ToonBackground.image_url`.

**Phase 4 — `generation_usage.episode_id`/`scene_id`/`attempts`.** Blocked on §3's resolution — an `episode_id` can be added now against `ToonEpisode` regardless, but `scene_id` has nowhere to point until/unless Scenes exist as their own entity.

**Phase 5 — Episode/Scene architecture.** **Blocked on §3.** Not started.

**Phases 6-12 (Kling provider, Voice provider, Toon assembly, QA, Publishing, Analytics, Autopilot)** — all except Autopilot are already built (see §1). Autopilot remains explicitly out of scope, unchanged from the prior session's decision.

Per this spec's own instruction ("Do not implement all phases in one operation"), only **Phase 1** is implemented in this turn. Phases 2-4 are ready to pick up on request; Phase 5 needs §3 resolved first.

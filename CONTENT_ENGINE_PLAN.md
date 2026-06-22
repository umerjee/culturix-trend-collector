# Culturix Content Engine — Video, Audio & Text (Agent 5: Media Generator)

Status: **Planning complete, ready for implementation.**
This is the Phase 2 build from `Culturix_Project_2026.docx` ("Add: video generation,
music generation, auto-posting"). Phase 1 (trend intelligence + text content ideas)
is largely done — see git log and `IMPLEMENTATION.md`.

This doc is the spec for Claude Code to implement while Umer is away. Work top to
bottom; each milestone is independently shippable and testable.

---

## 0. Current state (text engine — already built)

- `app/pipeline/nodes/content_strategist.py` (Agent 4) generates **10 ideas/profile**
  via Qwen (fallback Claude Haiku), each with: `hook`, `caption`, `cta`, `music_mood`,
  `platform`, `trend_connection`, `format`.
- Saved to `generated_content` table (`migrations/005_generated_content.sql`),
  threaded through `content_profile_id`.
- Frontend `DigestCard.tsx` renders each idea with copy-to-clipboard.
- **Text is functionally done.** The only text addition needed here is one new field:
  `video_prompt` (see Milestone 5).

---

## 1. Provider recommendations

The original plan doc recommends Chinese providers (Kling, MiniMax, iFlytek). Current
`.env` only has Anthropic/OpenAI/Voyage/Qwen keys — none of the media providers are
set up yet. Recommendation below optimizes for **fastest integration + lowest cost
for vertical short-form content**, while keeping a provider-abstraction layer so
swapping is cheap later.

| Need | Recommended | Why | Approx. cost |
|---|---|---|---|
| Video generation | **Kling API** (kling.ai/dev) | Cheapest per-second, vertical/social aesthetic matches TikTok/Reels per plan doc | $0.084–$0.168/sec |
| Voiceover (TTS) | **ElevenLabs API** | Industry-standard, easy REST API, voice cloning if needed later | Creator tier $11/mo (100k credits ≈ 100k chars) |
| Background music | **Suno API** (via aimlapi.com or sunoapi.org aggregator) | Best quality/flexibility, supports vocal + instrumental, matches `music_mood` field already generated | usage-based, ~$0.10–$0.30/track via aggregators |

**Alternative if multi-model flexibility is wanted later:** Runway API ($0.15/sec)
gives access to Veo, Kling, Seedance, Seedream through one API — worth revisiting once
volume justifies the higher per-second cost.

**New env vars to add to `.env` (and Railway):**
```
KLING_API_KEY=
ELEVENLABS_API_KEY=
SUNO_API_KEY=          # via aimlapi.com or sunoapi.org
SUPABASE_SERVICE_ROLE_KEY=   # needed for Storage uploads — currently commented out in .env
```

---

## 2. Architecture

```
[Content Strategist — Agent 4]
        │  10 ideas/profile (hook, caption, cta, music_mood, video_prompt, ...)
        ▼
[generated_content table]
        │
        │  user clicks "Generate" on a specific idea (on-demand, NOT batch —
        │  per plan doc: "Do NOT start with full AI video automation")
        ▼
[Media Generator — Agent 5]   app/media/
        ├── voice.py    → ElevenLabsProvider     → voiceover.mp3
        ├── music.py    → SunoProvider            → music.mp3
        └── video.py    → KlingProvider           → video.mp4
        │
        ▼
[Supabase Storage]  bucket: "media"
        │
        ▼
[generated_media table]  status: pending → processing → done/failed
        │
        ▼
[DigestCard.tsx]  shows player/preview once status=done (polling)
```

### New module: `app/media/`
```
app/media/
├── __init__.py
├── base.py          # MediaResult dataclass, VideoProvider/VoiceProvider/MusicProvider ABCs
├── voice.py          # ElevenLabsProvider
├── music.py          # SunoProvider
├── video.py          # KlingProvider
├── storage.py        # upload_to_supabase(bytes, path) -> public URL
└── service.py         # generate_media(content_id, idea_index, media_type) — orchestrates provider + storage + DB
```

`base.py` interface (all providers implement this so swapping = one new file):
```python
from dataclasses import dataclass
from abc import ABC, abstractmethod

@dataclass
class MediaResult:
    asset_bytes: bytes
    content_type: str       # "audio/mpeg", "video/mp4"
    duration_seconds: float | None = None
    cost_usd: float | None = None

class VoiceProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, voice: str | None = None) -> MediaResult: ...

class MusicProvider(ABC):
    @abstractmethod
    def generate(self, mood_prompt: str, duration_seconds: int = 30) -> MediaResult: ...

class VideoProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, duration_seconds: int = 5, aspect_ratio: str = "9:16") -> MediaResult: ...
```

---

## 3. Database

### Migration `migrations/006_generated_media.sql`
```sql
CREATE TABLE IF NOT EXISTS generated_media (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  generated_content_id UUID NOT NULL REFERENCES generated_content(id) ON DELETE CASCADE,
  idea_index           INT NOT NULL,           -- which of the 10 ideas (0-9)
  media_type           TEXT NOT NULL,          -- 'voiceover' | 'music' | 'video'
  provider             TEXT NOT NULL,          -- 'elevenlabs' | 'suno' | 'kling'
  status               TEXT NOT NULL DEFAULT 'pending',  -- pending|processing|done|failed
  prompt               TEXT,
  asset_url            TEXT,
  duration_seconds     NUMERIC,
  cost_usd             NUMERIC,
  error                TEXT,
  created_at           TIMESTAMPTZ DEFAULT NOW(),
  completed_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_generated_media_content
  ON generated_media(generated_content_id, idea_index);
```

### New model `app/models/generated_media.py`
SQLAlchemy model mirroring the table above (follow the style of
`app/models/generated_content.py`). Add to `app/models/__init__.py`.

---

## 4. Backend API (app/main.py)

Two new endpoints, following the existing `/api/generate` and `/api/digest/{user_id}`
naming convention (all user-facing endpoints live under `/api/...`):

- `POST /api/generate-media` — body: `{content_id, idea_index, media_types: ["voiceover","music","video"]}`
  - Inserts `generated_media` rows with `status=pending`
  - Kicks off generation via FastAPI `BackgroundTasks` (one task per media_type)
  - Returns the created row IDs immediately

- `GET /api/generate-media/{generated_content_id}` — returns all `generated_media` rows
  for that content_id (for the frontend to poll)

Each background task:
1. Sets `status=processing`
2. Calls the relevant provider in `app/media/service.py`
3. Uploads result to Supabase Storage bucket `media/{user_id}/{generated_content_id}/{idea_index}-{media_type}.{ext}`
4. Updates row: `status=done`, `asset_url`, `duration_seconds`, `cost_usd`, `completed_at`
   (or `status=failed`, `error=str(e)`)

---

## 5. Content Strategist update (small text addition)

Add one field to the JSON schema in `content_strategist._build_prompt()`:

- `video_prompt`: a cinematic/visual description for AI video generation (scene,
  camera movement, lighting, style) — max 40 words. This feeds `KlingProvider.generate()`.

This is the only change needed to the existing text pipeline. Update the
TypeScript `ContentIdea` interface in `culturix-web/src/lib/types.ts`
(currently: `hook, caption, cta, music_mood, platform, trend_connection, format?`)
to add `video_prompt?: string`.

---

## 6. Frontend (culturix-web)

- New proxy route `culturix-web/src/app/api/generate-media/route.ts` (mirrors
  `culturix-web/src/app/api/generate/route.ts` pattern — reads session, calls
  `${RAILWAY}/api/generate-media` on the backend)
- `DigestCard.tsx`: add a small action row with three buttons —
  "🎙 Voiceover", "🎵 Music", "🎬 Video" — each calls `/api/generate-media` with
  the relevant `media_type` and shows a spinner
- New component `MediaPreview.tsx`: polls `GET /api/generate-media/{content_id}`
  every ~5s while any item is `pending`/`processing`; renders `<audio>`/`<video>`
  player once `status=done`, or an error message if `failed`

---

## 7. Plan-tier gating (cost control)

Per the plan doc's "Most Important Advice" — do not auto-generate media for
everyone. Tie media generation to the existing `user_profiles.plan` column
(`'free'` | `'pro'`, added in the freemium commit):

- `plan='free'`: 0 media generations/month (buttons disabled, show upgrade prompt)
- `plan='pro'`: N generations/month — track usage via `COUNT(*) FROM generated_media
  WHERE generated_content_id IN (user's content) AND created_at >= date_trunc('month', now())`
  (no new table needed; query against `generated_media` directly)

---

## 8. Implementation order

1. **Migration + model**: `006_generated_media.sql`, `app/models/generated_media.py`,
   register in `__init__.py`
2. **Provider abstraction + ElevenLabs voiceover** (`app/media/base.py`,
   `app/media/voice.py`, `app/media/storage.py`, `app/media/service.py`) — start
   with voiceover only, it's cheapest and fastest to validate end-to-end
3. **API endpoints**: `POST /generate-media`, `GET /generate-media/{id}` (voiceover only)
4. **Frontend**: voiceover button + `MediaPreview.tsx` audio player, proxy route
5. **Add `video_prompt` field** to content_strategist + TS types
6. **Music provider** (`app/media/music.py` — Suno via aggregator)
7. **Video provider** (`app/media/video.py` — Kling)
8. **Plan-tier gating** for all three media types
9. **End-to-end test**: one content profile, generate all 3 media types for one idea,
   verify Supabase Storage URLs play correctly in the dashboard

---

## 9. New env vars checklist

Add to `.env` (local) and Railway project variables:
- `KLING_API_KEY`
- `ELEVENLABS_API_KEY`
- `SUNO_API_KEY`
- `SUPABASE_SERVICE_ROLE_KEY` (currently commented out — required for Storage uploads)

---

## 10. Open questions for Umer (non-blocking — implement with sensible defaults, flag in PR description)

- Voice: use a single default ElevenLabs voice for all profiles, or let users pick?
  → Default: one neutral voice to start, add selection later.
- Video duration: Kling default clip length? → Default: 5s, configurable later.
- Storage bucket privacy: public URLs vs signed URLs? → Default: public bucket
  `media/` (read-only), matches how content is meant to be shared/posted anyway.

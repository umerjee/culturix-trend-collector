export interface UserProfile {
  id?: string;
  user_id: string;
  target_age_min: number;
  target_age_max: number;
  target_platforms: string[];
  target_regions: string[];
  content_goals: string[];
  content_tones: string[];
  industry_niche: string;
  persona_tags: string[];
  delivery_freq: "daily" | "weekly";
  delivery_time: string;
  updated_at?: string;
}

export interface ContentProfile {
  id: string;
  user_id: string;
  name: string;
  industry_niche: string;
  target_platforms: string[];
  target_regions: string[];
  content_goals: string[];
  content_tones: string[];
  persona_tags: string[];
  target_age_min: number;
  target_age_max: number;
  delivery_freq: "daily" | "weekly";
  delivery_time: string;
  delivery_day_of_week?: number; // 0=Monday..6=Sunday, only meaningful when delivery_freq === "weekly"
  is_active: boolean;
  publish_mode?: "manual" | "review" | "auto";
  preferred_formats?: string[]; // subset of CONTENT_FORMATS keys; empty/unset = no restriction
  created_at?: string;
}

export interface ContentIdea {
  hook: string;
  caption: string;
  cta: string;
  music_mood: string;
  platform: string;
  trend_connection: string;
  format?: string;
  medium?: "video" | "photo" | "text"; // absent on ideas generated before this field existed — treat as "video"
  video_prompt?: string;
  viral_angle?: string;
  posting_time?: string;
  hashtag_strategy?: string;
  status?: "live" | "aging" | "stale" | "retired";
  relevance_score?: number;
  cluster_index?: number; // links this idea to digest.clusters[cluster_index]
  source?: "auto" | "on_demand";
}

export interface GeneratedMedia {
  id: string;
  idea_index: number;
  media_type: "voiceover" | "music" | "video" | "image" | "reel";
  provider: string;
  status: "pending" | "processing" | "done" | "failed";
  asset_url: string | null;
  duration_seconds: number | null;
  cost_usd: number | null;
  error: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface AccountSuggestions {
  recommended_platforms: { platform: string; reason: string }[];
  name_suggestions: { name: string; reason: string }[];
  bio_suggestion: string;
}

export interface ConnectedAccount {
  platform: "youtube" | "twitter" | "tiktok" | "instagram";
  platform_username: string | null;
  status: "active" | "expired" | "revoked" | "error";
  connected_at: string | null;
  // Which Trend profile (niche) this account is dedicated to — the user's own
  // "avatar account" for that niche. null = legacy/shared across all profiles.
  content_profile_id: string | null;
  // Which CultureToons brand ("toon account") this account is dedicated to —
  // the CultureToons analogue of content_profile_id above. Mutually
  // exclusive with it in practice.
  character_brand_id: string | null;
  // Whether a live "does this connection actually work" probe has been run —
  // distinct from `status`, which only reflects OAuth token lifecycle.
  last_tested_at: string | null;
  last_test_status: "ok" | "error" | null;
}

export interface ToonPost {
  id: string;
  toon_id: string;
  brand_id: string;
  platform: string;
  post_url: string | null;
  platform_post_id: string | null;
  status: "pending" | "tracked" | "failed" | "needs_reconnect";
  latest_views: number | null;
  latest_likes: number | null;
  latest_comments: number | null;
  latest_shares: number | null;
  last_fetched_at: string | null;
  error: string | null;
  created_at: string | null;
  posted_at: string | null;
}

export interface NextAutoPublish {
  candidate: { hook: string; platform: string; relevance_score: number | null } | null;
  reason?: "not_auto_mode" | "no_eligible_idea";
  scheduled_for?: string;
}

export interface ContentPost {
  id: string;
  generated_content_id: string;
  idea_index: number;
  platform: string;
  post_url: string | null;
  created_via: "manual" | "published" | "staged";
  status: "pending" | "fetching" | "tracked" | "failed" | "needs_reconnect" | "staged";
  latest_views: number | null;
  latest_likes: number | null;
  latest_comments: number | null;
  latest_shares: number | null;
  last_fetched_at: string | null;
  error: string | null;
  posted_at: string | null;
  created_at: string | null;
  hook?: string; // present only on the aggregate GET /api/content-posts feed
  caption_text: string | null;
  notification_status: "sent" | "failed" | null;
}

export interface TrendSignal {
  id: string;
  source: string;
  content_text: string;
  likes: number;
  collected_at: string;
}

export interface ClusterSummary {
  name: string;
  description: string;
  emotional_theme: string;
  why_it_matters: string;
  example_posts: string[];
}

export interface TrendCluster {
  id: number;
  theme: string;
  summary: string;
  size: number;
  momentum: "up" | "down" | "neutral" | null;
  previous_size: number | null;
  updated_at: string | null;
}

export interface Digest {
  id: string;
  user_id: string;
  content_profile_id?: string | null;
  generated_at: string;
  trend_date: string;
  clusters: ClusterSummary[];
  content_ideas: ContentIdea[];
  delivered: boolean;
}

// The platforms Culturix can actually connect/verify/track a post on — a
// subset of PLATFORMS below. Maps the LLM-facing display name (used in
// ContentIdea.platform, target_platforms, etc.) to the internal provider key
// app.social.service._PROVIDERS is keyed by. Single source of truth, reused
// by DigestCard.tsx, SettingsForm.tsx, and PublishingSetupStatus.tsx —
// previously duplicated separately in the first two.
export const CONNECTABLE_PLATFORMS: { key: string; label: string; display: string }[] = [
  { key: "youtube", label: "YouTube", display: "YouTube" },
  { key: "tiktok", label: "TikTok", display: "TikTok" },
  { key: "instagram", label: "Instagram", display: "Instagram" },
  { key: "twitter", label: "X / Twitter", display: "X/Twitter" },
];

export const PLATFORMS = ["TikTok", "YouTube", "Instagram", "Xiaohongshu", "X/Twitter", "Reddit", "Pinterest"] as const;

// Platforms offered as a target_platforms pick that Culturix can generate
// content ideas for, but can't connect an account to, publish to, or track
// performance on — derived from CONNECTABLE_PLATFORMS above so this can't
// drift the way target_regions/persona_tags used to (two independently
// maintained lists silently disagreeing). Not a hard filter like
// target_regions was — ideas targeting these still get generated normally,
// they just never show a Stage/Publish button (DigestCard.tsx's
// PUBLISHABLE_PLATFORMS lookup resolves to undefined for them, which
// degrades gracefully to "no button" rather than an error) — surfaced here
// so the picker is honest about the limitation instead of silently
// degrading later.
const _CONNECTABLE_DISPLAY_NAMES = CONNECTABLE_PLATFORMS.map((p) => p.display);
export const IDEAS_ONLY_PLATFORMS = PLATFORMS.filter(
  (p) => !_CONNECTABLE_DISPLAY_NAMES.includes(p)
);

// @deprecated — kept only as RegionChips.tsx's fallback if GET /api/regions
// is unreachable. app/regions.py is now the single source of truth (also
// used by persona_mapper.py's region filter) — don't add regions here
// without adding them there too, or you'll recreate the exact drift that
// caused a France-only profile to see zero clusters (FR offered here with
// no real collector tagging it) and makes "CN" a permanently empty option
// today (offered here, but its only tagger contributes zero rows).
export const REGIONS = ["US", "CN", "Global", "EU", "UK", "FR", "CA", "AU"] as const;
export const CONTENT_FORMATS = [
  { key: "video", label: "Video", description: "Short-form video — Reels, TikToks, Shorts" },
  { key: "photo", label: "Photo / Carousel", description: "Image posts and swipeable carousels" },
  { key: "text", label: "Text post", description: "Captions, threads, text-first posts" },
] as const;
export const DELIVERY_DAYS = [
  "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
] as const;
export const CONTENT_GOALS = [
  "Brand awareness",
  "Drive sales",
  "Community building",
  "Culture fit",
  "Education",
  "Entertainment",
] as const;
export const CONTENT_TONES = [
  "Dark luxury",
  "Educational",
  "Comedic",
  "Aspirational",
  "Authentic & raw",
  "Aesthetic",
  "Motivational",
  "Trendy & playful",
] as const;
export interface PersonaTag {
  name: string;
  description: string;
  momentum: "up" | "down" | "neutral" | null;
}

// @deprecated — kept only as a fallback for PersonaChips.tsx when GET
// /api/personas/active is unreachable or hasn't promoted anything yet (e.g.
// a fresh DB before the pipeline has run a few times). The live, momentum-
// tracked catalog (app/models/persona.py + persona_tag_tracker.py) is now
// the source of truth — don't add new tags here.
export const PERSONA_TAGS = [
  "Gen Z",
  "Millennials",
  "Anxious Ambitious",
  "Gymcore",
  "Cottagecore",
  "Dark Feminine",
  "Nepo Baby",
  "Quiet Luxury",
  "Bimbo Revival",
  "Clean Girl",
  "Looksmaxxing",
  "GRWM",
  "Corporate Girlie",
  "Soft Life",
  "Main Character",
  "That Girl",
] as const;

export interface AvatarTypePreset {
  key: string;
  label: string;
  emoji: string;
  description: string;
  industry_niche: string;
  target_platforms: string[];
  target_regions: string[];
  content_goals: string[];
  content_tones: string[];
  persona_tags: string[];
}

// Curated, data-backed starting points for a new trend/avatar profile — each
// pre-fills the profile form, which stays fully editable before saving.
// Chosen for durable, evergreen audience interest (not single-event spikes).
export const AVATAR_TYPES: AvatarTypePreset[] = [
  {
    key: "kpop",
    label: "K-pop & Global Fandom",
    emoji: "🎤",
    description: "Comebacks, chart activity, and fandom culture — one of the highest repost/share communities online.",
    industry_niche: "K-pop and global fandom culture",
    target_platforms: ["TikTok", "Instagram", "YouTube", "X/Twitter"],
    target_regions: ["Global"],
    content_goals: ["Community building", "Entertainment"],
    content_tones: ["Trendy & playful"],
    persona_tags: ["Gen Z", "Main Character"],
  },
  {
    key: "anime",
    label: "Anime & Japanese Pop Culture",
    emoji: "⛩️",
    description: "Evergreen global anime/manga fandom — not tied to any single release window.",
    industry_niche: "Anime and Japanese pop culture",
    target_platforms: ["TikTok", "YouTube", "Instagram"],
    target_regions: ["Global"],
    content_goals: ["Community building", "Entertainment"],
    content_tones: ["Trendy & playful", "Aesthetic"],
    persona_tags: ["Gen Z"],
  },
  {
    key: "gaming",
    label: "Gaming & Esports",
    emoji: "🎮",
    description: "Constant content firehose — game culture, esports, and gaming creators.",
    industry_niche: "Gaming and esports culture",
    target_platforms: ["TikTok", "YouTube", "X/Twitter"],
    target_regions: ["Global"],
    content_goals: ["Community building", "Entertainment"],
    content_tones: ["Comedic", "Trendy & playful"],
    persona_tags: ["Gen Z"],
  },
  {
    key: "streetwear",
    label: "Streetwear & Fashion",
    emoji: "👟",
    description: "Fit checks, drops, and street style — a proven niche already live in Culturix.",
    industry_niche: "Streetwear and fashion",
    target_platforms: ["Instagram", "TikTok", "Xiaohongshu"],
    target_regions: ["Global"],
    content_goals: ["Brand awareness", "Culture fit"],
    content_tones: ["Aesthetic", "Trendy & playful"],
    persona_tags: ["Quiet Luxury", "Main Character"],
  },
  {
    key: "beauty",
    label: "Beauty & Self-Care",
    emoji: "💄",
    description: "One of the most consistently strong niches on TikTok, Instagram, and Pinterest for years.",
    industry_niche: "Beauty and self-care",
    target_platforms: ["Instagram", "TikTok", "Pinterest"],
    target_regions: ["Global"],
    content_goals: ["Community building", "Brand awareness"],
    content_tones: ["Aesthetic", "Authentic & raw"],
    persona_tags: ["Clean Girl", "Soft Life", "That Girl"],
  },
];

export interface ShopifyStore {
  shop_domain: string;
  shop_name: string | null;
  currency: string | null;
  connected_at: string | null;
  last_synced_at: string | null;
  last_sync_status: "running" | "ok" | "error" | null;
  last_sync_error: string | null;
  product_count: number;
}

export interface ShopifyProductIdea {
  hook: string | null;
  caption: string | null;
  cta: string | null;
  hashtag_strategy: string | null;
  platform: string | null;
  generated_at: string | null;
}

export interface ShopifyProductReel {
  status: "processing" | "done" | "failed" | null;
  video_url: string | null;
  error: string | null;
  generated_at: string | null;
}

export interface ShopifyProduct {
  id: string;
  shopify_product_id: string;
  title: string;
  description: string | null;
  product_type: string | null;
  tags: string | null;
  price: string | null;
  currency: string | null;
  product_url: string | null;
  image_urls: string[];
  product_created_at: string | null;
  synced_at: string | null;
  idea: ShopifyProductIdea | null;
  reel: ShopifyProductReel | null;
}

export interface CharacterBrand {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  target_platforms: string[];
  delivery_freq: string;
  delivery_time: string;
  delivery_day_of_week: number;
  has_elevenlabs_key: boolean;
  // NULL means no cap set — budgets are opt-in per brand, not a default limit.
  daily_budget: number | null;
  monthly_budget: number | null;
  created_at: string | null;
  updated_at: string | null;
}

// Keep in sync with ART_STYLES in app/routers/culturetoons.py.
export const ART_STYLES = [
  { key: "cartoon_3d", label: "3D Pixar-style cartoon" },
  { key: "anime", label: "2D anime style" },
  { key: "flat_vector", label: "Flat vector illustration" },
  { key: "claymation", label: "Claymation style" },
  { key: "cinematic_cultural", label: "Cinematic cultural (painterly)" },
] as const;

// Character.personality's shape — see docs/culturix-comedy-architecture.md §3.2.
export interface CharacterPersonality {
  traits?: Record<string, number>;
  behavioral_rules?: string[];
  speech_rules?: string[];
}

// Fixed slider set for the personality editor — matches the spec's example
// trait names. Not exhaustive; any trait name is valid in the traits object,
// this is just what the UI offers sliders for by default.
export const PERSONALITY_TRAITS = [
  "confidence", "humor", "patience", "competitiveness",
  "warmth", "risk_tolerance", "formality", "impulsiveness",
] as const;

export interface Character {
  id: string;
  brand_id: string;
  name: string;
  description: string | null;
  base_image_url: string | null;
  reference_image_url: string | null;
  previous_image_urls: string[];
  art_style: (typeof ART_STYLES)[number]["key"];
  personality: CharacterPersonality | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export type ElementStatus = "unregistered" | "pending" | "ready" | "failed";
export type VoiceProvider = "kling" | "elevenlabs";

export interface CharacterVariant {
  id: string;
  character_id: string;
  name: string;
  culture_tag: string | null;
  description: string | null;
  image_url: string | null;
  reference_image_url: string | null;
  previous_image_urls: string[];
  persona_id: number | null;
  is_active: boolean;
  kling_element_id: string | null;
  kling_element_name: string | null;
  kling_voice_id: string | null;
  element_status: ElementStatus;
  element_error: string | null;
  voice_provider: VoiceProvider;
  elevenlabs_voice_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

// Character-level (not CharacterVariant-level) — see
// docs/culturix-comedy-architecture.md §3.4/decision 5.
export interface CharacterRelationship {
  id: string;
  brand_id: string;
  character_a_id: string;
  character_b_id: string;
  relationship_type: string | null;
  description: string | null;
  emotional_dynamic: string | null;
  conflict_level: number | null;
  trust_level: number | null;
  // Independent of trust_level — e.g. bickering siblings can be
  // low-trust but high-affection.
  affection_level: number | null;
  humor_dynamic: string | null;
  behavioral_rules: string[];
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export const RELATIONSHIP_EVENT_TYPES = [
  "conflict", "bonding", "running_joke", "betrayal", "reconciliation", "milestone", "general",
] as const;

// A timestamped entry in a relationship's history — distinct from
// CharacterRelationship's own static current-state fields above. See
// app/models/character_relationship_event.py.
export interface CharacterRelationshipEvent {
  id: string;
  relationship_id: string;
  brand_id: string;
  event_type: (typeof RELATIONSHIP_EVENT_TYPES)[number];
  description: string;
  affection_delta: number | null;
  trust_delta: number | null;
  conflict_delta: number | null;
  source_toon_id: string | null;
  source_episode_id: string | null;
  source_scene_id: string | null;
  created_at: string | null;
}

export const MEMORY_TYPES = [
  "backstory", "recurring_fact", "relationship_event",
  "previous_joke", "preference", "running_gag", "episode_event",
] as const;

export interface CharacterMemory {
  id: string;
  character_variant_id: string;
  brand_id: string;
  memory_type: (typeof MEMORY_TYPES)[number];
  content: string;
  importance: number | null;
  source_toon_id: string | null;
  created_at: string | null;
}

export interface BrandUsageByType {
  generation_type: string;
  count: number;
  cost_usd: number;
}

export interface BrandUsage {
  daily_budget: number | null;
  monthly_budget: number | null;
  daily_spend: number;
  monthly_spend: number;
  warning: string | null;
  this_month_by_type: BrandUsageByType[];
  unpriced_generations_this_month: number;
}

export const EXPRESSION_NAMES = [
  "Angry", "Confused", "Happy", "Shocked", "Laughing",
  "Side-eye", "Crying", "Annoyed", "Smiling", "Deadpan",
] as const;

export interface Expression {
  id: string;
  character_variant_id: string;
  name: (typeof EXPRESSION_NAMES)[number];
  image_url: string | null;
  created_at: string | null;
}

// "Locations" per docs/culturix-character-studio-upgrade.md §4 Phase 3 —
// same ToonBackground entity underneath, not renamed (see the model's own
// docstring for why).
export interface ToonBackground {
  id: string;
  brand_id: string;
  name: string;
  image_url: string | null;
  tags: string | null;
  description: string | null;
  country: string | null;
  visual_style: (typeof ART_STYLES)[number]["key"] | null;
  // Additional canonical angles/rooms of this same location, beyond image_url.
  reference_image_urls: string[];
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export const TONE_OPTIONS = ["funny", "dramatic", "satiric", "sad", "wholesome", "chaotic", "deadpan"] as const;

export interface ToonScriptShot {
  shot_number: number;
  duration_seconds: number;
  action: string;
  expression: (typeof EXPRESSION_NAMES)[number] | null;
  dialogue: string | null;
  speaker_variant_id?: string | null;
}

// Kling Omni's real per-call cap on distinct character elements — mirrors
// MAX_CHARACTERS_PER_VIDEO in app/services/culturetoon_video.py. Keep in
// sync; that constant's own comment flags it as an unverified assumption
// pending a real check against Kling's docs/dashboard.
export const MAX_CHARACTERS_PER_VIDEO = 3;

export interface ToonScript {
  id: string;
  brand_id: string;
  character_variant_id: string | null;
  character_variant_ids: string[];
  source_type: "persona" | "cluster" | "idea" | null;
  source_id: number | null;
  hook_line: string | null;
  dialogue: string | null;
  scene_direction: string | null;
  tone: (typeof TONE_OPTIONS)[number] | null;
  shots: ToonScriptShot[] | null;
  total_duration_seconds: number | null;
  background_id: string | null;
  generation_source: "manual" | "ai";
  status: "draft" | "approved" | "archived";
  created_at: string | null;
  updated_at: string | null;
}

export interface Toon {
  id: string;
  brand_id: string;
  character_variant_id: string;
  script_id: string;
  background_id: string | null;
  title: string | null;
  final_video_url: string | null;
  status: "idea" | "animating" | "ready" | "posted" | "archived" | "failed";
  platform: string | null;
  posted_at: string | null;
  notes: string | null;
  raw_video_url: string | null;
  clip_video_urls: string[];
  // Videos this toon had before its most recent regeneration, oldest
  // first — set by generate_video_for_toon so a regeneration never
  // silently discards a previous take.
  previous_video_urls: string[];
  // Set automatically right after generation (see
  // app/services/culturetoon_qa.py) — null means QA hasn't run yet.
  // publish_recommended is a soft signal only, never a hard server-side
  // block; a human always makes the final publish call.
  qa_results: {
    visual_score: number; comedy_score: number; cultural_score: number; technical_score: number;
    overall_score: number; publish_recommended: boolean; issues: string[];
    reasoning: string | null; judge_failed: boolean;
  } | null;
  publish_recommended: boolean | null;
  kling_task_id: string | null;
  generation_error: string | null;
  // Set when this Toon is one ordered "part" of a ToonEpisode (a longer
  // story stitched from several parts' raw_video_url) — null for a normal
  // standalone Toon.
  episode_id: string | null;
  part_order: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ToonEpisodePart {
  toon_id: string;
  order_index: number;
  status: Toon["status"];
  title: string | null;
  has_raw_video: boolean;
}

export interface ToonEpisode {
  id: string;
  brand_id: string;
  title: string | null;
  status: "draft" | "stitching" | "ready" | "failed" | "archived";
  final_video_url: string | null;
  clip_video_urls: string[];
  generation_error: string | null;
  parts: ToonEpisodePart[];
  created_at: string | null;
  updated_at: string | null;
}

// Independently-generated production unit within a ToonEpisode — an
// alternative to the Toon-parts path above (see app/models/toon_scene.py).
// Hard-deleted, not soft-delete, unlike every other CultureToons entity.
export interface ToonScene {
  id: string;
  episode_id: string;
  brand_id: string;
  scene_number: number;
  character_variant_ids: string[];
  background_id: string | null;
  action: string | null;
  dialogue: string | null;
  expression: string | null;
  camera_direction: string | null;
  duration_seconds: number;
  status: "idea" | "generating" | "ready" | "failed";
  video_url: string | null;
  previous_video_urls: string[];
  kling_task_id: string | null;
  generation_error: string | null;
  generation_attempts: number;
  created_at: string | null;
  updated_at: string | null;
}

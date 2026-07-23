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
  media_type: "voiceover" | "music" | "video" | "image";
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
  // Whether a live "does this connection actually work" probe has been run —
  // distinct from `status`, which only reflects OAuth token lifecycle.
  last_tested_at: string | null;
  last_test_status: "ok" | "error" | null;
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

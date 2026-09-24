// Mirrors app/routers/world.py's _serialize_feature — kept as one shared
// shape so every /world page/component agrees on what a Feature looks like.
export interface WorldFeature {
  id: string;
  title: string | null;
  subject_region: string | null;
  subject_text: string | null;
  subject_category: string | null;
  final_video_url: string | null;
  // The source article's own lead image — a real, topic-representative photo (see
  // CuratedItem.thumbnail_url on the backend). null for hand-made Features or a source
  // with no lead image; components fall back to a frame grabbed from final_video_url then.
  thumbnail_url: string | null;
  era_label: string | null;
  era_year: number | null;
  created_at: string | null;
  hook_line?: string | null; // only present on the single-feature detail response
  duration_seconds?: number | null; // detail response only
  source?: { label: string; url: string } | null; // detail response only — real Wikipedia/UNESCO attribution
  // The real narration lines the video's own audio speaks, in order — English by default, or
  // machine-translated into whatever `?lang=` was requested. Detail response only.
  transcript?: string[];
  transcript_language?: string;
  translation_failed?: boolean;
}

// Mirrors app/routers/world.py's get_world_trends_coverage — real
// earliest/latest/day-count for one region's Trend rows, used to size
// TimeCursor's "recent" zone honestly instead of a misleading fixed range.
export interface WorldTrendsCoverage {
  region: string;
  earliest: string | null;
  latest: string | null;
  days_with_data: number;
}

// Mirrors app/routers/world.py's _serialize_trend — real Trend rows,
// separate from generated-video Features above.
export interface WorldTrend {
  id: number;
  platform: string;
  title: string | null;
  content: string;
  url: string | null;
  likes: number | null;
  region: string | null;
  collected_at: string | null;
}

export interface WorldTrendDigestGroup {
  id: string;
  kind: "cluster" | "source";
  title: string;
  summary: string;
  signal_count: number;
  platforms: string[];
  momentum: "up" | "down" | "neutral" | null;
  signals: Pick<WorldTrend, "id" | "platform" | "title" | "likes" | "url" | "collected_at">[];
}

// Any code in app/translation/languages.py is accepted by the API; these are the
// ones offered in the picker. Keep the codes in sync with that registry.
export type WorldDigestLanguage = string;

export const DIGEST_LANGUAGES: { code: string; label: string }[] = [
  { code: "en", label: "English" }, { code: "fr", label: "Français" }, { code: "es", label: "Español" },
  { code: "de", label: "Deutsch" }, { code: "it", label: "Italiano" }, { code: "pt", label: "Português" },
  { code: "ar", label: "العربية" }, { code: "he", label: "עברית" }, { code: "hi", label: "हिन्दी" },
  { code: "ja", label: "日本語" }, { code: "ko", label: "한국어" }, { code: "zh-CN", label: "中文（简体）" },
  { code: "tr", label: "Türkçe" }, { code: "ru", label: "Русский" },
];

// Mirrors app/routers/world.py's get_region_summary — a short cached daily
// brief for a country. `summary` is null when a region has no brief that day
// (a normal state, not an error).
export interface WorldRegionSummary {
  region: string;
  region_name: string;
  date: string | null;
  summary: string | null;
  source: "ai" | "template" | "calendar" | null;
  calendar: { name: string; category: string; date: string; when: string; confirmed: boolean }[];
  signal_count: number;
  platforms: string[];
  mood: string | null;
  sentiment: number | null;
  alignment: "aligned" | "diverged" | "unknown" | null;
  vs_usual: "busier" | "quieter" | "normal" | null;
  generated_at: string | null;
  translation_failed?: boolean;
  // Real audience archetypes (Culturix's own cross-trend clustering) matched against today's
  // trends — never a real individual, never LLM-written. [] when nothing matched well.
  audience_matches: { name: string; description: string; content_angle: string | null; score: number }[];
}

// One merged filter vocabulary covering both WHAT a Feature is about
// (place/phenomenon/species/tech) and WHO it's most likely to resonate with
// (genz, more audience tags to follow) — a single flat list of filter chips
// on the map/grid, not two separate dimensions. subject_category is stored
// as free text (no DB enum), so adding a new tag here is just adding a
// label/icon, no migration. Content generation itself doesn't change based
// on category — this is a curation/discovery tag an admin assigns at
// creation time (see scripts/generate_world_feature.py --category), not a
// script-tone directive.
export const CATEGORY_LABELS: Record<string, string> = {
  place: "Places",
  phenomenon: "Phenomena",
  species: "Species",
  tech: "Technology",
  genz: "Gen-Z",
  custom: "More",
};

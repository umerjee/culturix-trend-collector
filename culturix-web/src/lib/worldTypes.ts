// Mirrors app/routers/world.py's _serialize_feature — kept as one shared
// shape so every /world page/component agrees on what a Feature looks like.
export interface WorldFeature {
  id: string;
  title: string | null;
  subject_region: string | null;
  subject_text: string | null;
  subject_category: string | null;
  final_video_url: string | null;
  created_at: string | null;
  hook_line?: string | null; // only present on the single-feature detail response
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

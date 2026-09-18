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

export const CATEGORY_LABELS: Record<string, string> = {
  place: "Places",
  phenomenon: "Phenomena",
  species: "Species",
  tech: "Technology",
  custom: "More",
};

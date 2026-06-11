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
  is_active: boolean;
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
  video_prompt?: string;
}

export interface GeneratedMedia {
  id: string;
  idea_index: number;
  media_type: "voiceover" | "music" | "video";
  provider: string;
  status: "pending" | "processing" | "done" | "failed";
  asset_url: string | null;
  duration_seconds: number | null;
  cost_usd: number | null;
  error: string | null;
  created_at: string | null;
  completed_at: string | null;
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

export const PLATFORMS = ["TikTok", "YouTube", "Instagram", "Xiaohongshu", "X/Twitter", "Reddit"] as const;
export const REGIONS = ["US", "CN", "Global", "EU", "UK", "FR", "CA", "AU"] as const;
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

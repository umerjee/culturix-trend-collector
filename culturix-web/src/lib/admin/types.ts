// Shared admin domain types — extracted from the former monolithic
// AdminDashboard.tsx so each routed admin page can import just what it needs.

export interface Trend {
  id: number;
  platform: string;
  content: string;
  author: string;
  url: string;
  likes: number;
  comments: number;
  language: string;
  collected_at: string | null;
}

export interface Cluster {
  id: number;
  label: number;
  description: string;
  trend_count: number;
  created_at: string | null;
  momentum?: "up" | "down" | "neutral" | null;
  previous_size?: number | null;
}

export interface ClusterDetail {
  id: number;
  theme: string | null;
  summary: string | null;
  size: number;
  trends: { id: number; platform: string; title: string; url: string | null; collected_at: string | null }[];
}

export interface Persona {
  id: number;
  name: string;
  description: string;
  motivations: string[];
  interests: string[];
  status?: "pending" | "active" | "dormant";
  momentum?: "up" | "down" | "neutral" | null;
  created_at: string | null;
}

export interface ContentSuggestion {
  title: string;
  format: string;
  hook: string;
  platform: string;
}

export interface PersonaDetail {
  id: number;
  name: string;
  description: string;
  motivations: string | null;
  interests: string | null;
  content_suggestions: ContentSuggestion[] | null;
  status?: "pending" | "active" | "dormant";
  momentum?: "up" | "down" | "neutral" | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  // Populated only for legacy rows from the now-superseded per-cluster
  // generation path — always empty for new-style personas, which use
  // PersonaOccurrence (occurrences fetched separately) instead.
  sample_trends: { id: number; platform: string; title: string; url: string | null }[];
}

export interface TrendTheme {
  id: number;
  canonical_name: string;
  description: string | null;
  emotional_theme: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  occurrence_count: number;
  recurrence_pattern: "weekly" | "yearly" | "sustained" | "spike" | "unclear" | null;
  dominant_day_of_week: number | null;
  pattern_confidence: number | null;
}

export interface TrendOccurrence {
  id: number;
  occurrence_date: string;
  day_of_week: number;
  name_snapshot: string | null;
  description_snapshot: string | null;
  size: number | null;
  durability: string | null;
}

export interface Digest {
  id: string;
  user_id: string;
  generated_at: string | null;
  trend_date: string;
  cluster_count: number;
  idea_count: number;
  delivered: boolean;
}

export interface ContentProfileRecord {
  id: string;
  name: string;
  industry_niche: string | null;
  target_platforms: string[];
  is_active: boolean;
  created_at: string | null;
}

export interface UserRecord {
  id: string;
  user_id: string;
  approved: boolean;
  plan: "free" | "pro";
  created_at: string | null;
  // This month's actual idea-generation activity — proactive is the 3
  // free daily ideas (same for every plan), on_demand is the pro-gated
  // "Generate" button for additional trends (see
  // app/media/quota.py::plan_blocks_extra_ideas). Lets an admin verify a
  // pro user is actually using what they're paying for, or spot a free
  // user who should be (successfully or not) hitting the gate.
  proactive_ideas_this_month: number;
  on_demand_ideas_this_month: number;
  content_profiles: ContentProfileRecord[];
}

export interface ValidationLogEntry {
  id: string;
  source: string;
  subject: string;
  legitimate: boolean | null;
  safe: boolean | null;
  durability: string | null;
  status: "approved" | "rejected";
  reason: string | null;
  checked_at: string | null;
}

export interface ContentCheckLogEntry {
  id: string;
  generated_content_id: string;
  idea_index: number | null;
  checked_at: string | null;
  previous_score: number | null;
  new_score: number | null;
  trend_score: number | null;
  freshness_score: number | null;
  persona_score: number | null;
  previous_status: string | null;
  new_status: string | null;
  action_taken: string | null;
}

export interface HighVelocityAlert {
  id: number;
  platform: string;
  external_id: string;
  description: string | null;
  velocity_score: number | null;
  like_count: number | null;
  view_count: number | null;
  trend_posted_at: string | null;
  received_at: string | null;
}

export interface IntegrationHealthEntry {
  integration: string;
  status: string;
  error: string | null;
  checked_at: string | null;
}

export interface AdminStats {
  total_trends: number;
  total_clusters: number;
  total_personas: number;
  total_users: number;
  total_digests: number;
  by_platform: Record<string, number>;
}

export function fmt(dt: string | null): string {
  if (!dt) return "—";
  const d = new Date(dt);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
    ", " + d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

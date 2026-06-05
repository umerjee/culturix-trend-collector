// All requests go through Next.js rewrites → localhost:8000
const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json();
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Trend {
  id: number;
  platform: string;
  title: string;
  content: string;
  translated_content: string | null;
  language: string | null;
  url: string | null;
  author: string | null;
  likes: number | null;
  comments: number | null;
  views: number | null;
  cluster_id: number | null;
  collected_at: string;
  posted_at: string | null;
}

export interface Cluster {
  id: number;
  label: number;
  theme: string | null;
  summary: string | null;
  size: number;
  created_at: string;
  sample_trends: { id: number; platform: string; title: string }[];
}

export interface ClusterDetail extends Cluster {
  trends: { id: number; platform: string; title: string; url: string | null; collected_at: string }[];
}

export interface ContentSuggestion {
  title: string;
  format: string;
  hook: string;
  platform: string;
}

export interface Persona {
  id: number;
  name: string;
  description: string;
  motivations: string | null;
  interests: string | null;
  content_suggestions: ContentSuggestion[] | null;
  created_at: string;
}

export interface PersonaDetail extends Persona {
  sample_trends: { id: number; platform: string; title: string; url: string | null }[];
}

export interface Stats {
  trends: number;
  embedded: number;
  clustered: number;
  clusters: number;
  personas: number;
}

// ── Fetchers ──────────────────────────────────────────────────────────────────

export const fetcher = (url: string) => fetch(url).then((r) => r.json());

export const api = {
  trends: (params?: { platform?: string; language?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    if (params?.platform) q.set("platform", params.platform);
    if (params?.language) q.set("language", params.language);
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.offset) q.set("offset", String(params.offset));
    return `/api/trends/latest${q.toString() ? "?" + q : ""}`;
  },
  trend: (id: number) => `/api/trends/${id}`,
  clusters: () => `/api/clusters`,
  cluster: (id: number) => `/api/clusters/${id}`,
  personas: () => `/api/personas`,
  persona: (id: number) => `/api/personas/${id}`,
  search: (q: string, platform?: string) => {
    const params = new URLSearchParams({ q });
    if (platform) params.set("platform", platform);
    return `/api/search?${params}`;
  },
  recommendations: (personaId?: number, clusterId?: number) => {
    const params = new URLSearchParams();
    if (personaId) params.set("persona_id", String(personaId));
    if (clusterId) params.set("cluster_id", String(clusterId));
    return `/api/recommendations${params.toString() ? "?" + params : ""}`;
  },
};

import type { MetadataRoute } from "next";
import { RAILWAY_API_BASE } from "@/lib/config/api";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://culturixcloud.com";

// Viewer-first public site: the pages worth indexing are the videos and the country pages, not
// sign-up or the (closed) creator products. Refreshed hourly; if the backend is down the static
// pages are still listed.
export const revalidate = 3600;

async function getJson(path: string): Promise<any> {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}${path}`, { next: { revalidate: 3600 }, signal: AbortSignal.timeout(8000) });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();
  const [features, regions] = await Promise.all([getJson("/world/features?limit=100"), getJson("/world/regions")]);

  const videoPages: MetadataRoute.Sitemap = (features?.features ?? []).map((f: { id: string; created_at: string | null }) => ({
    url: `${SITE_URL}/world/feature/${f.id}`,
    lastModified: f.created_at ? new Date(f.created_at) : now,
    changeFrequency: "monthly",
    priority: 0.7,
  }));
  const countryPages: MetadataRoute.Sitemap = (regions?.regions ?? [])
    .filter((r: { feature_count?: number }) => (r.feature_count ?? 0) > 0)
    .map((r: { region: string }) => ({
      url: `${SITE_URL}/world/region/${r.region}`,
      lastModified: now,
      changeFrequency: "daily",
      priority: 0.6,
    }));

  return [
    { url: `${SITE_URL}/`, lastModified: now, changeFrequency: "daily", priority: 1 },
    { url: `${SITE_URL}/world`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    ...videoPages,
    ...countryPages,
    { url: `${SITE_URL}/privacy`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
    { url: `${SITE_URL}/terms`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
  ];
}

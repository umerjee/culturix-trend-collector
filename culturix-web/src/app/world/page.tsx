import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";
import WorldExplorer from "@/components/world/WorldExplorer";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import { WORLD_FEED_PAGE_SIZE } from "@/lib/worldTypes";
import type { WorldFeature } from "@/lib/worldTypes";

export const metadata = {
  alternates: { canonical: "/world" },
  title: { absolute: "Culturix World — the AI video encyclopedia of the world" },
  description:
    "The AI video encyclopedia of the world, with a sense of humour: short, source-linked videos about real places, phenomena, species and technology. Browse the feed or explore by place.",
};

async function fetchFirstPage(
  region?: string, category?: string, q?: string,
): Promise<{ features: WorldFeature[]; total: number; error: boolean }> {
  try {
    const params = new URLSearchParams({ limit: String(WORLD_FEED_PAGE_SIZE), offset: "0" });
    if (region) params.set("region", region);
    if (category) params.set("category", category);
    if (q) params.set("q", q);
    const res = await fetch(`${RAILWAY_API_BASE}/world/features?${params.toString()}`, {
      cache: "no-store",
      // Confirmed live 2026-09-30: without a timeout a slow backend hung this fetch until
      // Vercel's function timeout killed the whole page with a raw "Application error".
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) return { features: [], total: 0, error: true };
    const data = await res.json();
    const features: WorldFeature[] = Array.isArray(data.features) ? data.features : [];
    return { features, total: typeof data.total === "number" ? data.total : features.length, error: false };
  } catch {
    // Reported as an error (the feed shows Retry), never as an empty library.
    return { features: [], total: 0, error: true };
  }
}

export default async function WorldPage({
  searchParams,
}: {
  searchParams: { region?: string; category?: string; q?: string };
}) {
  const { features, total, error } = await fetchFirstPage(searchParams.region, searchParams.category, searchParams.q);

  return (
    <div className="min-h-screen bg-white">
      <MarketingHeader showCta={false} />

      <main className="max-w-6xl mx-auto px-4 sm:px-6">
        <WorldExplorer
          initialFeatures={features}
          initialTotal={total}
          initialError={error}
          initialCategory={searchParams.category}
          initialRegion={searchParams.region}
          initialQuery={searchParams.q}
        />
      </main>

      <MarketingFooter />
    </div>
  );
}

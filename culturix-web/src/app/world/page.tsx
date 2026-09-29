import { Globe2 } from "lucide-react";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";
import WorldExplorer from "@/components/world/WorldExplorer";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import type { WorldFeature } from "@/lib/worldTypes";

export const metadata = {
  title: "World — Culturix",
  description:
    "A visual atlas of the world's cultural, technological and funny traits — short AI-generated videos about real places, phenomena and species, organized by region.",
};

async function fetchFeatures(region?: string, category?: string, q?: string): Promise<WorldFeature[]> {
  try {
    const params = new URLSearchParams({ limit: "24" });
    if (region) params.set("region", region);
    if (category) params.set("category", category);
    if (q) params.set("q", q);
    const res = await fetch(`${RAILWAY_API_BASE}/world/features?${params.toString()}`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.features) ? data.features : [];
  } catch {
    return [];
  }
}

export default async function WorldPage({
  searchParams,
}: {
  searchParams: { region?: string; category?: string; q?: string };
}) {
  const features = await fetchFeatures(searchParams.region, searchParams.category, searchParams.q);

  return (
    <div className="min-h-screen bg-white">
      <MarketingHeader />

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-14">
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-2 rounded-full bg-purple-50 border border-purple-200 text-purple-600 text-xs font-semibold px-3 py-1.5 mb-6">
            <Globe2 className="h-3.5 w-3.5" />
            Culturix World
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 mb-4">
            A visual atlas of the world
          </h1>
          <p className="text-gray-500 max-w-xl mx-auto leading-relaxed">
            Short AI-generated videos about real places, phenomena and species — grounded in real
            trend data. Click a country or a theme on the map to explore, or search.
          </p>
        </div>

        <WorldExplorer
          initialFeatures={features}
          initialCategory={searchParams.category}
          initialRegion={searchParams.region}
          initialQuery={searchParams.q}
        />
      </main>

      <MarketingFooter />
    </div>
  );
}

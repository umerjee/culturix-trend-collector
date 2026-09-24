import { Globe2, Search } from "lucide-react";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";
import WorldMap from "@/components/world/WorldMap";
import CategoryGrid from "@/components/world/CategoryGrid";
import FeatureCard from "@/components/world/FeatureCard";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import type { WorldFeature } from "@/lib/worldTypes";

export const metadata = {
  title: "World — Culturix",
  description:
    "A visual atlas of the world's cultural, technological and funny traits — short AI-generated videos about real places, phenomena and species, organized by region.",
};

async function fetchFeatures(category?: string, q?: string): Promise<WorldFeature[]> {
  try {
    const params = new URLSearchParams({ limit: "24" });
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
  searchParams: { category?: string; q?: string };
}) {
  const features = await fetchFeatures(searchParams.category, searchParams.q);

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
            trend data, organized by region. Browse the map, pick a theme, or search.
          </p>
        </div>

        <section className="mb-10">
          <WorldMap />
        </section>

        <section id="categories" className="mb-10 scroll-mt-20">
          <CategoryGrid />
        </section>

        <form action="/world" className="mb-8 max-w-md mx-auto">
          <div className="relative">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              name="q"
              defaultValue={searchParams.q}
              placeholder="Search places, phenomena, species..."
              className="w-full rounded-xl border border-gray-200 pl-10 pr-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-300"
            />
          </div>
        </form>

        {features.length === 0 ? (
          <p className="text-center text-sm text-gray-400 py-10">
            {searchParams.q || searchParams.category
              ? "No Features match that filter yet."
              : "No World Features published yet — check back soon."}
          </p>
        ) : (
          <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
            {features.map((f) => (
              <FeatureCard key={f.id} feature={f} />
            ))}
          </section>
        )}
      </main>

      <MarketingFooter />
    </div>
  );
}

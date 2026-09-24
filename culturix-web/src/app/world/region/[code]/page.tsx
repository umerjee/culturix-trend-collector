import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import countries from "i18n-iso-countries";
import enLocale from "i18n-iso-countries/langs/en.json";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";
import FeatureCard from "@/components/world/FeatureCard";
import RegionFactsStrip from "@/components/world/RegionFactsStrip";
import TimeCursor from "@/components/world/TimeCursor";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import type { WorldFeature, WorldRegionSummary, WorldTrend, WorldTrendsCoverage } from "@/lib/worldTypes";

countries.registerLocale(enLocale as any);

async function fetchFeatures(region: string): Promise<WorldFeature[]> {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/features?region=${encodeURIComponent(region)}&limit=48`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.features) ? data.features : [];
  } catch {
    return [];
  }
}

async function fetchTrends(region: string): Promise<WorldTrend[]> {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/trends?region=${encodeURIComponent(region)}&limit=12`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.trends) ? data.trends : [];
  } catch {
    return [];
  }
}

async function fetchCoverage(region: string): Promise<WorldTrendsCoverage> {
  const empty: WorldTrendsCoverage = { region, earliest: null, latest: null, days_with_data: 0 };
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/trends/coverage?region=${encodeURIComponent(region)}`, {
      cache: "no-store",
    });
    if (!res.ok) return empty;
    return await res.json();
  } catch {
    return empty;
  }
}

async function fetchBrief(region: string): Promise<WorldRegionSummary | null> {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/regions/${encodeURIComponent(region)}/summary`, { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    // `facts` is static reference data, independent of whether a daily summary has been
    // generated yet — a region with no brief today can still have a capital/population/etc.
    return data?.summary || data?.facts ? data : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: { code: string } }) {
  const label = countries.getName(params.code.toUpperCase(), "en") || params.code.toUpperCase();
  return { title: `${label} — Culturix World` };
}

export default async function WorldRegionPage({ params }: { params: { code: string } }) {
  const code = params.code.toUpperCase();
  const label = countries.getName(code, "en") || code;
  const [features, trends, coverage, brief] = await Promise.all([fetchFeatures(code), fetchTrends(code), fetchCoverage(code), fetchBrief(code)]);

  return (
    <div className="min-h-screen bg-white">
      <MarketingHeader />

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-14">
        <Link href="/world" className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-purple-600 mb-8">
          <ArrowLeft className="h-3.5 w-3.5" /> All regions
        </Link>

        <h1 className="text-3xl font-bold text-gray-900 mb-2">{label}</h1>
        <p className="text-gray-500 mb-10">What&apos;s trending in {label} today, and the videos Culturix has published about it.</p>

        <RegionFactsStrip facts={brief?.facts ?? null} />

        <TimeCursor region={code} regionLabel={label} coverage={coverage} initialTrends={trends} initialBrief={brief} />

        <section className="mt-14">
          <div className="mb-5 flex items-end justify-between gap-4">
            <h2 className="text-lg font-semibold text-gray-900">Culturix World videos</h2>
            <span className="text-xs text-gray-400">{features.length} published</span>
          </div>
          {features.length === 0 ? (
            <p className="text-sm text-gray-400 py-6">No videos published for {label} yet — check back soon.</p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
              {features.map((f) => (
                <FeatureCard key={f.id} feature={f} />
              ))}
            </div>
          )}
        </section>
      </main>

      <MarketingFooter />
    </div>
  );
}

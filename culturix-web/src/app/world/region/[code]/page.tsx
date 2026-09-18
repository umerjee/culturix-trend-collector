import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import countries from "i18n-iso-countries";
import enLocale from "i18n-iso-countries/langs/en.json";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";
import FeatureCard from "@/components/world/FeatureCard";
import TimeCursor from "@/components/world/TimeCursor";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import type { WorldFeature, WorldRegionSummary, WorldTrend, WorldTrendDigestGroup, WorldTrendsCoverage } from "@/lib/worldTypes";

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

async function fetchDigest(region: string): Promise<WorldTrendDigestGroup[]> {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/trends/digest?region=${encodeURIComponent(region)}&limit=8`, { cache: "no-store" });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.groups) ? data.groups : [];
  } catch {
    return [];
  }
}

async function fetchBrief(region: string): Promise<WorldRegionSummary | null> {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/regions/${encodeURIComponent(region)}/summary`, { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    return data?.summary ? data : null;
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
  const [features, trends, coverage, digest, brief] = await Promise.all([fetchFeatures(code), fetchTrends(code), fetchCoverage(code), fetchDigest(code), fetchBrief(code)]);

  return (
    <div className="min-h-screen bg-white">
      <MarketingHeader />

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-14">
        <Link href="/world" className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-purple-600 mb-8">
          <ArrowLeft className="h-3.5 w-3.5" /> All regions
        </Link>

        <h1 className="text-3xl font-bold text-gray-900 mb-2">{label}</h1>
        <p className="text-gray-500 mb-10">
          {features.length} Feature{features.length === 1 ? "" : "s"} from this region.
        </p>

        {features.length === 0 ? (
          <p className="text-sm text-gray-400 py-10">Nothing published for {label} yet — check back soon.</p>
        ) : (
          <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5 mb-14">
            {features.map((f) => (
              <FeatureCard key={f.id} feature={f} />
            ))}
          </section>
        )}

        <TimeCursor region={code} regionLabel={label} coverage={coverage} initialTrends={trends} initialDigest={digest} initialBrief={brief} />
      </main>

      <MarketingFooter />
    </div>
  );
}

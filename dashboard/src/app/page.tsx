import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TrendingUp, Network, Users, Database } from "lucide-react";
import { fetcher, api, type Trend, type Cluster, type Persona } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { PlatformBadge } from "@/components/ui/badge";
import Link from "next/link";

async function getStats() {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const [trends, clusters, personas]: [Trend[], Cluster[], Persona[]] = await Promise.all([
    fetch(`${base}/trends/latest?limit=100`, { cache: "no-store" }).then((r) => r.json()),
    fetch(`${base}/clusters`, { cache: "no-store" }).then((r) => r.json()),
    fetch(`${base}/personas`, { cache: "no-store" }).then((r) => r.json()),
  ]);
  return { trends, clusters, personas };
}

export default async function OverviewPage() {
  let trends: Trend[] = [];
  let clusters: Cluster[] = [];
  let personas: Persona[] = [];
  let error = false;

  try {
    const data = await getStats();
    trends = data.trends;
    clusters = data.clusters;
    personas = data.personas;
  } catch {
    error = true;
  }

  const platformCounts = trends.reduce<Record<string, number>>((acc, t) => {
    acc[t.platform] = (acc[t.platform] ?? 0) + 1;
    return acc;
  }, {});

  const statCards = [
    { label: "Trends collected", value: trends.length, icon: TrendingUp, color: "text-blue-600 bg-blue-50" },
    { label: "Clusters", value: clusters.length, icon: Network, color: "text-violet-600 bg-violet-50" },
    { label: "Personas", value: personas.length, icon: Users, color: "text-emerald-600 bg-emerald-50" },
    { label: "Platforms", value: Object.keys(platformCounts).length, icon: Database, color: "text-orange-600 bg-orange-50" },
  ];

  return (
    <div className="p-4 sm:p-8 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Overview</h1>
        <p className="text-muted-foreground mt-1">Cultural intelligence at a glance</p>
      </div>

      {error && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Could not reach the API. Check that the backend is deployed and the{" "}
          <code className="font-mono">NEXT_PUBLIC_API_URL</code> environment variable is set.
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4 mb-8">
        {statCards.map(({ label, value, icon: Icon, color }) => (
          <Card key={label}>
            <CardContent className="p-6">
              <div className={`inline-flex rounded-lg p-2 ${color} mb-3`}>
                <Icon className="h-5 w-5" />
              </div>
              <p className="text-3xl font-bold">{value}</p>
              <p className="text-sm text-muted-foreground mt-1">{label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Recent trends */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center justify-between">
              Recent Trends
              <Link href="/trends" className="text-sm font-normal text-blue-600 hover:underline">View all →</Link>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y">
              {trends.slice(0, 8).map((t) => (
                <li key={t.id} className="flex items-center gap-3 px-6 py-3">
                  <PlatformBadge platform={t.platform} />
                  <span className="text-sm truncate flex-1">{t.title || t.content?.slice(0, 60)}</span>
                  <span className="text-xs text-muted-foreground whitespace-nowrap">{formatDate(t.collected_at)}</span>
                </li>
              ))}
              {trends.length === 0 && !error && (
                <li className="px-6 py-4 text-sm text-muted-foreground">No trends yet — run the collectors.</li>
              )}
            </ul>
          </CardContent>
        </Card>

        {/* Clusters */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center justify-between">
              Top Clusters
              <Link href="/clusters" className="text-sm font-normal text-blue-600 hover:underline">View all →</Link>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y">
              {clusters.slice(0, 6).map((c) => (
                <li key={c.id} className="px-6 py-3">
                  <Link href={`/clusters/${c.id}`} className="group">
                    <p className="text-sm font-medium group-hover:text-blue-600 transition-colors">
                      {c.theme ?? `Cluster ${c.label}`}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">{c.summary}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{c.size} trends</p>
                  </Link>
                </li>
              ))}
              {clusters.length === 0 && !error && (
                <li className="px-6 py-4 text-sm text-muted-foreground">No clusters yet — run /process/cluster.</li>
              )}
            </ul>
          </CardContent>
        </Card>

        {/* Personas */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center justify-between">
              Personas
              <Link href="/personas" className="text-sm font-normal text-blue-600 hover:underline">View all →</Link>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y">
              {personas.slice(0, 5).map((p) => (
                <li key={p.id} className="px-6 py-3">
                  <Link href={`/personas/${p.id}`} className="group flex items-start gap-4">
                    <div className="h-9 w-9 shrink-0 rounded-full bg-gradient-to-br from-violet-400 to-blue-500 flex items-center justify-center text-white font-bold text-sm">
                      {p.name[0]}
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium group-hover:text-blue-600 transition-colors">{p.name}</p>
                      <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">{p.description}</p>
                    </div>
                  </Link>
                </li>
              ))}
              {personas.length === 0 && !error && (
                <li className="px-6 py-4 text-sm text-muted-foreground">No personas yet — run /process/personas/clustered.</li>
              )}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { Zap, LayoutDashboard, TrendingUp, Layers, Users, Search, LogOut } from "lucide-react";

interface Trend {
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

interface Cluster {
  id: number;
  label: number;
  description: string;
  trend_count: number;
  created_at: string | null;
}

interface Persona {
  id: number;
  name: string;
  description: string;
  motivations: string[];
  interests: string[];
  created_at: string | null;
}

interface Digest {
  id: string;
  user_id: string;
  generated_at: string | null;
  trend_date: string;
  cluster_count: number;
  idea_count: number;
  delivered: boolean;
}

interface Props {
  trends: Trend[];
  clusters: Cluster[];
  personas: Persona[];
  digests: Digest[];
  apiUrl: string;
}

type Page = "overview" | "trends" | "clusters" | "personas" | "search";

const PLATFORM_BADGE: Record<string, string> = {
  youtube: "bg-red-100 text-red-600",
  twitter: "bg-sky-100 text-sky-600",
  reddit: "bg-orange-100 text-orange-600",
  tiktok: "bg-pink-100 text-pink-600",
};

function fmt(dt: string | null) {
  if (!dt) return "—";
  const d = new Date(dt);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
    ", " + d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function PlatformBadge({ platform }: { platform: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold capitalize ${PLATFORM_BADGE[platform] ?? "bg-gray-100 text-gray-500"}`}>
      {platform === "youtube" ? "YouTube" : platform.charAt(0).toUpperCase() + platform.slice(1)}
    </span>
  );
}

function StatCard({ icon, value, label }: { icon: React.ReactNode; value: number | string; label: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-6 flex flex-col gap-3">
      <div className="h-10 w-10 rounded-xl bg-gray-50 flex items-center justify-center text-gray-500">
        {icon}
      </div>
      <div>
        <p className="text-3xl font-bold text-gray-900">{value}</p>
        <p className="text-sm text-gray-500 mt-0.5">{label}</p>
      </div>
    </div>
  );
}

export default function AdminDashboard({ trends, clusters, personas, digests, apiUrl }: Props) {
  const [page, setPage] = useState<Page>("overview");
  const [search, setSearch] = useState("");
  const [platformFilter, setPlatformFilter] = useState("all");
  const [collecting, setCollecting] = useState(false);
  const [collectMsg, setCollectMsg] = useState("");

  const byPlatform = trends.reduce<Record<string, number>>((acc, t) => {
    acc[t.platform] = (acc[t.platform] ?? 0) + 1;
    return acc;
  }, {});
  const platformCount = Object.keys(byPlatform).length;

  const filteredTrends = trends.filter((t) => {
    if (platformFilter !== "all" && t.platform !== platformFilter) return false;
    if (search && !t.content.toLowerCase().includes(search.toLowerCase()) &&
        !(t.author ?? "").toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  async function triggerCollect() {
    setCollecting(true);
    setCollectMsg("");
    try {
      const res = await fetch("/api/admin/collect", { method: "POST" });
      setCollectMsg(res.ok ? "Collection started — refresh in ~60s" : `Error ${res.status}`);
    } catch (e) {
      setCollectMsg(`Error: ${e}`);
    }
    setCollecting(false);
  }

  const nav: { key: Page; icon: React.ReactNode; label: string }[] = [
    { key: "overview", icon: <LayoutDashboard className="h-4 w-4" />, label: "Overview" },
    { key: "trends", icon: <TrendingUp className="h-4 w-4" />, label: "Trends" },
    { key: "clusters", icon: <Layers className="h-4 w-4" />, label: "Clusters" },
    { key: "personas", icon: <Users className="h-4 w-4" />, label: "Personas" },
    { key: "search", icon: <Search className="h-4 w-4" />, label: "Search" },
  ];

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-48 shrink-0 bg-white border-r border-gray-100 flex flex-col">
        {/* Logo */}
        <div className="h-16 flex items-center gap-2 px-5 border-b border-gray-100">
          <Zap className="h-5 w-5 text-blue-600" />
          <span className="font-bold text-base tracking-tight text-gray-900">Culturix</span>
        </div>

        {/* Nav items */}
        <nav className="flex-1 py-4 space-y-0.5 px-2">
          {nav.map(({ key, icon, label }) => (
            <button
              key={key}
              onClick={() => { setPage(key); if (key === "search") setSearch(""); }}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors text-left ${
                page === key
                  ? "bg-blue-50 text-blue-600"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
              }`}
            >
              {icon}
              {label}
            </button>
          ))}
        </nav>

        {/* Back to dashboard */}
        <div className="p-3 border-t border-gray-100">
          <a
            href="/dashboard"
            className="flex items-center gap-2 px-3 py-2 text-xs text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <LogOut className="h-3.5 w-3.5" />
            Back to app
          </a>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-16 bg-white border-b border-gray-100 flex items-center justify-between px-8">
          <div>
            <h1 className="font-bold text-gray-900 capitalize">
              {page === "overview" ? "Overview" : page.charAt(0).toUpperCase() + page.slice(1)}
            </h1>
            {page === "overview" && (
              <p className="text-xs text-gray-400">Cultural intelligence at a glance</p>
            )}
          </div>
          <div className="flex items-center gap-3">
            {collectMsg && <span className="text-xs text-gray-400">{collectMsg}</span>}
            <button
              onClick={triggerCollect}
              disabled={collecting}
              className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {collecting ? "Collecting…" : "Collect now"}
            </button>
          </div>
        </header>

        {/* Scrollable body */}
        <main className="flex-1 overflow-y-auto px-8 py-8">

          {/* ── Overview ── */}
          {page === "overview" && (
            <div className="space-y-8">
              {/* Stat cards */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <StatCard
                  icon={<TrendingUp className="h-5 w-5" />}
                  value={trends.length}
                  label="Trends collected"
                />
                <StatCard
                  icon={<Layers className="h-5 w-5" />}
                  value={clusters.length}
                  label="Clusters"
                />
                <StatCard
                  icon={<Users className="h-5 w-5" />}
                  value={personas.length}
                  label="Personas"
                />
                <StatCard
                  icon={<LayoutDashboard className="h-5 w-5" />}
                  value={platformCount}
                  label="Platforms"
                />
              </div>

              <div className="grid lg:grid-cols-2 gap-6">
                {/* Recent trends */}
                <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
                  <div className="flex items-center justify-between px-6 py-4 border-b border-gray-50">
                    <h2 className="font-semibold text-gray-900 text-sm">Recent Trends</h2>
                    <button onClick={() => setPage("trends")} className="text-xs text-blue-600 hover:underline">
                      View all →
                    </button>
                  </div>
                  <ul className="divide-y divide-gray-50">
                    {trends.slice(0, 8).map((t) => (
                      <li key={t.id} className="flex items-center gap-3 px-6 py-3">
                        <PlatformBadge platform={t.platform} />
                        <span className="flex-1 text-sm text-gray-700 truncate">{t.content}</span>
                        <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">{fmt(t.collected_at)}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Top clusters */}
                <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
                  <div className="flex items-center justify-between px-6 py-4 border-b border-gray-50">
                    <h2 className="font-semibold text-gray-900 text-sm">Top Clusters</h2>
                    <button onClick={() => setPage("clusters")} className="text-xs text-blue-600 hover:underline">
                      View all →
                    </button>
                  </div>
                  {clusters.length === 0 && (
                    <p className="text-sm text-gray-400 px-6 py-8">No clusters yet — run the pipeline.</p>
                  )}
                  <ul className="divide-y divide-gray-50">
                    {clusters.slice(0, 6).map((c) => (
                      <li key={c.id} className="px-6 py-4">
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <p className="font-semibold text-sm text-gray-900">{c.description || `Cluster ${c.label}`}</p>
                          </div>
                          <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">
                            {c.trend_count ?? 0} trends
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              {/* Digest history strip */}
              {digests.length > 0 && (
                <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
                  <div className="px-6 py-4 border-b border-gray-50">
                    <h2 className="font-semibold text-gray-900 text-sm">Recent Digests</h2>
                  </div>
                  <div className="divide-y divide-gray-50">
                    {digests.slice(0, 5).map((d) => (
                      <div key={d.id} className="flex items-center gap-4 px-6 py-3 text-sm">
                        <span className="text-gray-400 text-xs font-mono">{d.id.slice(0, 8)}…</span>
                        <span className="text-gray-600 flex-1">{fmt(d.generated_at)}</span>
                        <span className="text-gray-400">{d.cluster_count} clusters · {d.idea_count} ideas</span>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${d.delivered ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                          {d.delivered ? "Delivered" : "Pending"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Trends ── */}
          {page === "trends" && (
            <div className="space-y-4">
              <div className="flex gap-3 flex-wrap">
                <select
                  value={platformFilter}
                  onChange={(e) => setPlatformFilter(e.target.value)}
                  className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white"
                >
                  <option value="all">All platforms</option>
                  {Object.keys(byPlatform).map((p) => (
                    <option key={p} value={p}>{p} ({byPlatform[p]})</option>
                  ))}
                </select>
                <span className="text-sm text-gray-400 self-center">{filteredTrends.length} trends</span>
              </div>
              <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-50 bg-gray-50">
                      <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Platform</th>
                      <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Content</th>
                      <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Engagement</th>
                      <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Collected</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {filteredTrends.slice(0, 200).map((t) => (
                      <tr key={t.id} className="hover:bg-gray-50">
                        <td className="px-6 py-3"><PlatformBadge platform={t.platform} /></td>
                        <td className="px-6 py-3 max-w-sm">
                          {t.url ? (
                            <a href={t.url} target="_blank" rel="noreferrer" className="text-gray-800 hover:text-blue-600 line-clamp-2">
                              {t.content}
                            </a>
                          ) : (
                            <span className="text-gray-800 line-clamp-2">{t.content}</span>
                          )}
                        </td>
                        <td className="px-6 py-3 text-gray-400 whitespace-nowrap text-xs">
                          ♥ {(t.likes ?? 0).toLocaleString()} &middot; 💬 {(t.comments ?? 0).toLocaleString()}
                        </td>
                        <td className="px-6 py-3 text-gray-400 text-xs whitespace-nowrap">{fmt(t.collected_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── Clusters ── */}
          {page === "clusters" && (
            <div className="space-y-3">
              {clusters.length === 0 && (
                <p className="text-gray-400 text-sm">No clusters yet — run the pipeline first.</p>
              )}
              {clusters.map((c) => (
                <div key={c.id} className="bg-white rounded-xl border border-gray-100 px-6 py-5 flex items-start justify-between gap-6">
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-gray-900">{c.description || `Cluster ${c.label}`}</p>
                    <p className="text-xs text-gray-400 mt-1">{fmt(c.created_at)}</p>
                  </div>
                  <span className="text-xs text-gray-500 whitespace-nowrap shrink-0 bg-gray-50 px-3 py-1 rounded-full">
                    {c.trend_count ?? 0} trends
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* ── Personas ── */}
          {page === "personas" && (
            <div className="grid md:grid-cols-2 gap-4">
              {personas.length === 0 && (
                <p className="text-gray-400 text-sm col-span-2">No personas yet — run the pipeline first.</p>
              )}
              {personas.map((p) => (
                <div key={p.id} className="bg-white rounded-xl border border-gray-100 p-6 space-y-3">
                  <h3 className="font-semibold text-gray-900">{p.name}</h3>
                  <p className="text-sm text-gray-500">{p.description}</p>
                  {p.interests?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {p.interests.slice(0, 8).map((i, idx) => (
                        <span key={idx} className="px-2 py-0.5 bg-purple-50 text-purple-600 rounded text-xs">{i}</span>
                      ))}
                    </div>
                  )}
                  {p.motivations?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {p.motivations.slice(0, 5).map((m, idx) => (
                        <span key={idx} className="px-2 py-0.5 bg-amber-50 text-amber-600 rounded text-xs">{m}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* ── Search ── */}
          {page === "search" && (
            <div className="space-y-4">
              <input
                autoFocus
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search trends by keyword, author, or content…"
                className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              {search.length > 0 && (
                <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
                  <div className="px-6 py-3 border-b border-gray-50 text-xs text-gray-400">
                    {filteredTrends.length} results for &ldquo;{search}&rdquo;
                  </div>
                  <ul className="divide-y divide-gray-50">
                    {filteredTrends.slice(0, 50).map((t) => (
                      <li key={t.id} className="flex items-center gap-3 px-6 py-3">
                        <PlatformBadge platform={t.platform} />
                        <span className="flex-1 text-sm text-gray-700 truncate">{t.content}</span>
                        <span className="text-xs text-gray-400 whitespace-nowrap">{fmt(t.collected_at)}</span>
                      </li>
                    ))}
                    {filteredTrends.length === 0 && (
                      <li className="px-6 py-8 text-center text-sm text-gray-400">No trends match your search.</li>
                    )}
                  </ul>
                </div>
              )}
            </div>
          )}

        </main>
      </div>
    </div>
  );
}

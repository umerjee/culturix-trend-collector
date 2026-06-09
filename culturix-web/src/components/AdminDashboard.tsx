"use client";

import { useState } from "react";

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
  label: string;
  description: string;
  trend_count: number;
  created_at: string | null;
}

interface Persona {
  id: number;
  name: string;
  description: string;
  motivations: string[] | null;
  interests: string[] | null;
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

const PLATFORM_COLORS: Record<string, string> = {
  youtube: "bg-red-100 text-red-700",
  twitter: "bg-sky-100 text-sky-700",
  reddit: "bg-orange-100 text-orange-700",
  tiktok: "bg-pink-100 text-pink-700",
};

function Badge({ text, className }: { text: string; className?: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${className ?? "bg-gray-100 text-gray-600"}`}>
      {text}
    </span>
  );
}

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className="text-3xl font-bold text-gray-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

export default function AdminDashboard({ trends, clusters, personas, digests, apiUrl }: Props) {
  const [tab, setTab] = useState<"trends" | "clusters" | "personas" | "digests">("trends");
  const [search, setSearch] = useState("");
  const [platformFilter, setPlatformFilter] = useState("all");
  const [collecting, setCollecting] = useState(false);
  const [collectMsg, setCollectMsg] = useState("");

  const byPlatform = trends.reduce<Record<string, number>>((acc, t) => {
    acc[t.platform] = (acc[t.platform] ?? 0) + 1;
    return acc;
  }, {});

  const filteredTrends = trends.filter((t) => {
    if (platformFilter !== "all" && t.platform !== platformFilter) return false;
    if (search && !t.content.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  async function triggerCollect() {
    setCollecting(true);
    setCollectMsg("Starting collection…");
    try {
      const res = await fetch(`${apiUrl}/admin/collect`, { method: "POST" });
      if (res.ok) {
        setCollectMsg("Collection started in background. Refresh in ~60s.");
      } else {
        setCollectMsg(`Error: ${res.status}`);
      }
    } catch (e) {
      setCollectMsg(`Error: ${e}`);
    }
    setCollecting(false);
  }

  const tabs = [
    { key: "trends" as const, label: `Trends (${trends.length})` },
    { key: "clusters" as const, label: `Clusters (${clusters.length})` },
    { key: "personas" as const, label: `Personas (${personas.length})` },
    { key: "digests" as const, label: `Digests (${digests.length})` },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Culturix Admin</h1>
          <p className="text-xs text-gray-500 mt-0.5">Super admin dashboard</p>
        </div>
        <div className="flex items-center gap-3">
          {collectMsg && <span className="text-xs text-gray-500">{collectMsg}</span>}
          <button
            onClick={triggerCollect}
            disabled={collecting}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition"
          >
            {collecting ? "…" : "Collect now"}
          </button>
          <a href="/dashboard" className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
            ← Dashboard
          </a>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-8 space-y-8">
        {/* Stats row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Total trends" value={trends.length} />
          <StatCard label="Clusters" value={clusters.length} />
          <StatCard label="Personas" value={personas.length} />
          <StatCard label="Digests generated" value={digests.length} />
        </div>

        {/* Platform breakdown */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Trends by platform</h2>
          <div className="flex flex-wrap gap-3">
            {Object.entries(byPlatform).map(([platform, count]) => (
              <div key={platform} className="flex items-center gap-2">
                <Badge text={platform} className={PLATFORM_COLORS[platform] ?? "bg-gray-100 text-gray-600"} />
                <span className="text-sm font-medium text-gray-700">{count}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Tabs */}
        <div>
          <div className="flex gap-1 border-b border-gray-200 mb-5">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`px-4 py-2 text-sm font-medium border-b-2 transition -mb-px ${
                  tab === t.key
                    ? "border-indigo-600 text-indigo-600"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Trends tab */}
          {tab === "trends" && (
            <div className="space-y-3">
              <div className="flex gap-3 flex-wrap">
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search trends…"
                  className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[200px]"
                />
                <select
                  value={platformFilter}
                  onChange={(e) => setPlatformFilter(e.target.value)}
                  className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm"
                >
                  <option value="all">All platforms</option>
                  {Object.keys(byPlatform).map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
                <span className="text-sm text-gray-500 self-center">{filteredTrends.length} results</span>
              </div>
              <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Platform</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Content</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Engagement</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Collected</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {filteredTrends.slice(0, 200).map((t) => (
                      <tr key={t.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3">
                          <Badge text={t.platform} className={PLATFORM_COLORS[t.platform] ?? "bg-gray-100 text-gray-600"} />
                        </td>
                        <td className="px-4 py-3 max-w-md">
                          {t.url ? (
                            <a href={t.url} target="_blank" rel="noreferrer" className="text-gray-800 hover:text-indigo-600 line-clamp-2">
                              {t.content}
                            </a>
                          ) : (
                            <span className="text-gray-800 line-clamp-2">{t.content}</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                          ♥ {(t.likes ?? 0).toLocaleString()} · 💬 {(t.comments ?? 0).toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-gray-400 whitespace-nowrap text-xs">
                          {t.collected_at ? new Date(t.collected_at).toLocaleDateString() : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Clusters tab */}
          {tab === "clusters" && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {clusters.length === 0 && (
                <p className="text-gray-500 col-span-3">No clusters yet. Run the pipeline to generate them.</p>
              )}
              {clusters.map((c) => (
                <div key={c.id} className="bg-white rounded-xl border border-gray-200 p-5 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold text-gray-800">{c.label}</h3>
                    <Badge text={`${c.trend_count} trends`} className="bg-indigo-50 text-indigo-600 shrink-0" />
                  </div>
                  <p className="text-sm text-gray-500 line-clamp-3">{c.description}</p>
                  <p className="text-xs text-gray-400">
                    {c.created_at ? new Date(c.created_at).toLocaleDateString() : ""}
                  </p>
                </div>
              ))}
            </div>
          )}

          {/* Personas tab */}
          {tab === "personas" && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {personas.length === 0 && (
                <p className="text-gray-500 col-span-2">No personas yet. Run the pipeline to generate them.</p>
              )}
              {personas.map((p) => (
                <div key={p.id} className="bg-white rounded-xl border border-gray-200 p-5 space-y-3">
                  <h3 className="font-semibold text-gray-800">{p.name}</h3>
                  <p className="text-sm text-gray-500">{p.description}</p>
                  {p.interests && p.interests.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {p.interests.slice(0, 8).map((i, idx) => (
                        <Badge key={idx} text={i} className="bg-purple-50 text-purple-600" />
                      ))}
                    </div>
                  )}
                  {p.motivations && p.motivations.length > 0 && (
                    <div>
                      <p className="text-xs text-gray-400 mb-1">Motivations</p>
                      <div className="flex flex-wrap gap-1.5">
                        {p.motivations.slice(0, 5).map((m, idx) => (
                          <Badge key={idx} text={m} className="bg-amber-50 text-amber-600" />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Digests tab */}
          {tab === "digests" && (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">ID</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">User</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Date</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Clusters</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Ideas</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Delivered</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {digests.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-gray-400">No digests yet.</td>
                    </tr>
                  )}
                  {digests.map((d) => (
                    <tr key={d.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono text-xs text-gray-400">{d.id.slice(0, 8)}…</td>
                      <td className="px-4 py-3 font-mono text-xs text-gray-500">{d.user_id.slice(0, 8)}…</td>
                      <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                        {d.generated_at ? new Date(d.generated_at).toLocaleString() : "—"}
                      </td>
                      <td className="px-4 py-3 text-gray-600">{d.cluster_count}</td>
                      <td className="px-4 py-3 text-gray-600">{d.idea_count}</td>
                      <td className="px-4 py-3">
                        <Badge
                          text={d.delivered ? "Yes" : "No"}
                          className={d.delivered ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

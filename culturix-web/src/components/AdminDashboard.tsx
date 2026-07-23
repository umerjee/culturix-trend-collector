"use client";

import { useState, useEffect } from "react";
import { Zap, LayoutDashboard, TrendingUp, Layers, Users, Search, LogOut, CheckCircle, XCircle, Clock, RefreshCw, History, ArrowUpRight, ArrowDownRight, Minus, ExternalLink, Lightbulb } from "lucide-react";

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
  momentum?: "up" | "down" | "neutral" | null;
  previous_size?: number | null;
}

interface ClusterDetail {
  id: number;
  theme: string | null;
  summary: string | null;
  size: number;
  trends: { id: number; platform: string; title: string; url: string | null; collected_at: string | null }[];
}

interface Persona {
  id: number;
  name: string;
  description: string;
  motivations: string[];
  interests: string[];
  status?: "pending" | "active" | "dormant";
  momentum?: "up" | "down" | "neutral" | null;
  created_at: string | null;
}

interface ContentSuggestion {
  title: string;
  format: string;
  hook: string;
  platform: string;
}

interface PersonaDetail {
  id: number;
  name: string;
  description: string;
  motivations: string | null;
  interests: string | null;
  content_suggestions: ContentSuggestion[] | null;
  status?: "pending" | "active" | "dormant";
  momentum?: "up" | "down" | "neutral" | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  // Populated only for legacy rows from the now-superseded per-cluster
  // generation path — always empty for new-style personas, which use
  // PersonaOccurrence (see personaOccurrences state) instead.
  sample_trends: { id: number; platform: string; title: string; url: string | null }[];
}

interface TrendTheme {
  id: number;
  canonical_name: string;
  description: string | null;
  emotional_theme: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  occurrence_count: number;
  recurrence_pattern: "weekly" | "yearly" | "sustained" | "spike" | "unclear" | null;
  dominant_day_of_week: number | null;
  pattern_confidence: number | null;
}

interface TrendOccurrence {
  id: number;
  occurrence_date: string;
  day_of_week: number;
  name_snapshot: string | null;
  description_snapshot: string | null;
  size: number | null;
  durability: string | null;
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

interface ContentProfileRecord {
  id: string;
  name: string;
  industry_niche: string | null;
  target_platforms: string[];
  is_active: boolean;
  created_at: string | null;
}

interface UserRecord {
  id: string;
  user_id: string;
  approved: boolean;
  plan: "free" | "pro";
  created_at: string | null;
  content_profiles: ContentProfileRecord[];
}

type Page = "overview" | "trends" | "clusters" | "personas" | "history" | "users" | "search";

async function fetchData(type: string) {
  const res = await fetch(`/api/admin/data?type=${type}`, { cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`${type} → HTTP ${res.status}: ${JSON.stringify(body)}`);
  return body;
}

async function fetchDetail(type: string, id: number | string) {
  const res = await fetch(`/api/admin/data?type=${type}&id=${id}`, { cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`${type} → HTTP ${res.status}: ${JSON.stringify(body)}`);
  return body;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WEEKDAYS_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const PATTERN_BADGE: Record<string, string> = {
  weekly: "bg-blue-100 text-blue-700",
  yearly: "bg-violet-100 text-violet-700",
  sustained: "bg-green-100 text-green-700",
  spike: "bg-orange-100 text-orange-700",
  unclear: "bg-gray-100 text-gray-500",
};
const PATTERN_LABEL: Record<string, string> = {
  weekly: "Weekly", yearly: "Yearly", sustained: "Sustained", spike: "Spike", unclear: "Unclear",
};
const PATTERN_ORDER = ["weekly", "yearly", "sustained", "spike", "unclear"];

function PatternBadge({ pattern }: { pattern: string | null }) {
  const p = pattern ?? "unclear";
  return (
    <span className={`shrink-0 px-2 py-0.5 rounded text-xs font-semibold ${PATTERN_BADGE[p] ?? PATTERN_BADGE.unclear}`}>
      {PATTERN_LABEL[p] ?? "Unclear"}
    </span>
  );
}

function MomentumBadge({ momentum }: { momentum?: "up" | "down" | "neutral" | null }) {
  if (!momentum) return null;
  if (momentum === "up") {
    return <span className="inline-flex items-center gap-0.5 text-xs font-semibold text-green-600"><ArrowUpRight className="h-3.5 w-3.5" /> Rising</span>;
  }
  if (momentum === "down") {
    return <span className="inline-flex items-center gap-0.5 text-xs font-semibold text-red-500"><ArrowDownRight className="h-3.5 w-3.5" /> Falling</span>;
  }
  return <span className="inline-flex items-center gap-0.5 text-xs font-medium text-gray-400"><Minus className="h-3.5 w-3.5" /> Steady</span>;
}

// Occurrence count per weekday, single-hue bars (magnitude, not identity) —
// the dominant day (if any) is rendered as the darker step of the same hue.
function WeekdayBarChart({ occurrences, dominantDay }: { occurrences: TrendOccurrence[]; dominantDay: number | null }) {
  const counts = [0, 0, 0, 0, 0, 0, 0];
  occurrences.forEach((o) => { if (o.day_of_week >= 0 && o.day_of_week <= 6) counts[o.day_of_week] += 1; });
  const max = Math.max(...counts, 1);

  return (
    <div className="flex items-end gap-2 h-28">
      {counts.map((count, i) => (
        <div key={i} className="flex-1 flex flex-col items-center gap-1.5">
          <div className="w-full flex flex-col justify-end h-20">
            <div
              className={`w-full rounded-t transition-colors ${i === dominantDay ? "bg-blue-600" : "bg-blue-200 hover:bg-blue-300"}`}
              style={{ height: count === 0 ? "2px" : `${Math.max((count / max) * 100, 8)}%` }}
              title={`${WEEKDAYS_FULL[i]}: ${count} occurrence${count !== 1 ? "s" : ""}`}
            />
          </div>
          <span className={`text-[10px] font-medium ${i === dominantDay ? "text-blue-600" : "text-gray-400"}`}>{WEEKDAYS[i]}</span>
        </div>
      ))}
    </div>
  );
}

// Dot-plot timeline of occurrence dates between first and last seen —
// makes recurrence (evenly spaced dots) vs a one-off burst (clustered dots) visible at a glance.
function OccurrenceTimeline({ occurrences }: { occurrences: TrendOccurrence[] }) {
  if (occurrences.length === 0) {
    return <p className="text-xs text-gray-400">No occurrences yet.</p>;
  }
  const dates = occurrences.map((o) => new Date(o.occurrence_date).getTime()).sort((a, b) => a - b);
  const min = dates[0];
  const max = dates[dates.length - 1];
  const span = Math.max(max - min, 1);

  return (
    <div className="relative h-9">
      <div className="absolute inset-x-0 top-1/2 h-px bg-gray-200" />
      {dates.map((d, i) => (
        <div
          key={i}
          className="absolute top-1/2 h-2.5 w-2.5 rounded-full bg-blue-600 ring-2 ring-white hover:scale-125 transition-transform cursor-default"
          style={{ left: `${(( d - min) / span) * 100}%`, transform: "translate(-50%, -50%)" }}
          title={new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
        />
      ))}
      <div className="absolute inset-x-0 -bottom-1 flex justify-between text-[10px] text-gray-400">
        <span>{new Date(min).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
        {max !== min && <span>{new Date(max).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>}
      </div>
    </div>
  );
}

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

export default function AdminDashboard() {
  const [page, setPage] = useState<Page>("overview");
  const [search, setSearch] = useState("");
  const [platformFilter, setPlatformFilter] = useState("all");
  const [collecting, setCollecting] = useState(false);
  const [collectMsg, setCollectMsg] = useState("");
  const [approving, setApproving] = useState<string | null>(null);

  const [trends, setTrends] = useState<Trend[]>([]);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [digests, setDigests] = useState<Digest[]>([]);
  const [userList, setUserList] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [trendHistory, setTrendHistory] = useState<TrendTheme[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [selectedThemeId, setSelectedThemeId] = useState<number | null>(null);
  const [occurrences, setOccurrences] = useState<TrendOccurrence[]>([]);
  const [occurrencesLoading, setOccurrencesLoading] = useState(false);

  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null);
  const [clusterDetail, setClusterDetail] = useState<ClusterDetail | null>(null);
  const [clusterDetailLoading, setClusterDetailLoading] = useState(false);

  const [selectedPersonaId, setSelectedPersonaId] = useState<number | null>(null);
  const [personaDetail, setPersonaDetail] = useState<PersonaDetail | null>(null);
  const [personaDetailLoading, setPersonaDetailLoading] = useState(false);
  const [personaOccurrences, setPersonaOccurrences] = useState<TrendOccurrence[]>([]);

  async function loadAll() {
    setLoading(true);
    setError(null);
    const results = await Promise.allSettled([
      fetchData("trends"),
      fetchData("clusters"),
      fetchData("personas"),
      fetchData("digests"),
      fetchData("users"),
    ]);
    const [t, c, p, d, u] = results;
    const firstErr = results.find(r => r.status === "rejected") as PromiseRejectedResult | undefined;
    if (firstErr) setError(firstErr.reason?.message ?? String(firstErr.reason));
    setTrends(t.status === "fulfilled" && Array.isArray(t.value) ? t.value : []);
    setClusters(c.status === "fulfilled" && Array.isArray(c.value) ? c.value : []);
    setPersonas(p.status === "fulfilled" && Array.isArray(p.value) ? p.value : []);
    setDigests(d.status === "fulfilled" && Array.isArray(d.value) ? d.value : []);
    setUserList(u.status === "fulfilled" && Array.isArray(u.value) ? u.value : []);
    setLoading(false);
  }

  useEffect(() => { loadAll(); }, []);

  useEffect(() => {
    if (page === "history" && !historyLoaded) {
      setHistoryLoaded(true);
      fetchData("trend-history")
        .then((data) => setTrendHistory(Array.isArray(data) ? data : []))
        .catch(() => setTrendHistory([]));
    }
  }, [page, historyLoaded]);

  async function selectTheme(id: number) {
    setSelectedThemeId(id);
    setOccurrencesLoading(true);
    try {
      const data = await fetchDetail("trend-history-occurrences", id);
      setOccurrences(Array.isArray(data) ? data : []);
    } catch {
      setOccurrences([]);
    } finally {
      setOccurrencesLoading(false);
    }
  }

  async function selectCluster(id: number) {
    setSelectedClusterId(id);
    setClusterDetailLoading(true);
    try {
      setClusterDetail(await fetchDetail("cluster-detail", id));
    } catch {
      setClusterDetail(null);
    } finally {
      setClusterDetailLoading(false);
    }
  }

  async function selectPersona(id: number) {
    setSelectedPersonaId(id);
    setPersonaDetailLoading(true);
    try {
      const [detail, occurrences] = await Promise.all([
        fetchDetail("persona-detail", id),
        fetchDetail("persona-occurrences", id).catch(() => []),
      ]);
      setPersonaDetail(detail);
      setPersonaOccurrences(Array.isArray(occurrences) ? occurrences : []);
    } catch {
      setPersonaDetail(null);
      setPersonaOccurrences([]);
    } finally {
      setPersonaDetailLoading(false);
    }
  }

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

  async function setApproval(userId: string, approved: boolean) {
    setApproving(userId);
    try {
      const action = approved ? "approve" : "reject";
      const res = await fetch(`/api/admin/users/${userId}/${action}`, { method: "POST" });
      if (res.ok) {
        setUserList((prev) => prev.map((u) => u.user_id === userId ? { ...u, approved } : u));
      }
    } finally {
      setApproving(null);
    }
  }

  async function setPlan(userId: string, plan: "free" | "pro") {
    const res = await fetch(`/api/admin/users/${userId}/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan }),
    });
    if (res.ok) {
      setUserList((prev) => prev.map((u) => u.user_id === userId ? { ...u, plan } : u));
    }
  }

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
    { key: "history", icon: <History className="h-4 w-4" />, label: "History" },
    { key: "users" as const, icon: <Users className="h-4 w-4" />, label: `Users${userList.filter(u => !u.approved).length ? ` (${userList.filter(u => !u.approved).length})` : ""}` },
    { key: "search", icon: <Search className="h-4 w-4" />, label: "Search" },
  ];

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-center space-y-3">
          <RefreshCw className="h-8 w-8 text-blue-500 animate-spin mx-auto" />
          <p className="text-sm text-gray-500">Loading admin data…</p>
        </div>
      </div>
    );
  }

  // error shown inline as banner, not blocking

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
              onClick={loadAll}
              className="px-3 py-1.5 border border-gray-200 text-gray-600 text-sm rounded-lg hover:bg-gray-50 transition inline-flex items-center gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
            <button
              onClick={triggerCollect}
              disabled={collecting}
              className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {collecting ? "Collecting…" : "Collect now"}
            </button>
            <a
              href="/dashboard"
              className="px-4 py-1.5 border border-gray-200 text-gray-600 text-sm rounded-lg hover:bg-gray-50 transition"
            >
              ← User dashboard
            </a>
          </div>
        </header>

        {/* Scrollable body */}
        <main className="flex-1 overflow-y-auto px-8 py-8">
          {error && (
            <div className="mb-6 bg-red-50 border border-red-200 rounded-xl px-5 py-3 text-sm text-red-700 font-mono break-all">
              ⚠ {error}
            </div>
          )}

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
            <div className="grid lg:grid-cols-[1fr,1.1fr] gap-6 items-start lg:h-[calc(100vh-11rem)]">
              <div className="space-y-3 lg:h-full lg:overflow-y-auto lg:pr-1">
                {clusters.length === 0 && (
                  <p className="text-gray-400 text-sm">No clusters yet — run the pipeline first.</p>
                )}
                {clusters.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => selectCluster(c.id)}
                    className={`w-full text-left bg-white rounded-xl border px-6 py-5 flex items-start justify-between gap-6 transition-colors ${
                      selectedClusterId === c.id ? "border-blue-300 ring-1 ring-blue-100" : "border-gray-100 hover:border-gray-200"
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-gray-900">{c.description || `Cluster ${c.label}`}</p>
                      <div className="flex items-center gap-3 mt-1.5">
                        <span className="text-xs text-gray-400">{fmt(c.created_at)}</span>
                        <MomentumBadge momentum={c.momentum} />
                      </div>
                    </div>
                    <span className="text-xs text-gray-500 whitespace-nowrap shrink-0 bg-gray-50 px-3 py-1 rounded-full">
                      {c.trend_count ?? 0} trends
                    </span>
                  </button>
                ))}
              </div>

              <div className="bg-white rounded-xl border border-gray-100 p-6 lg:h-full lg:overflow-y-auto">
                {!selectedClusterId && (
                  <p className="text-sm text-gray-400 text-center py-16">Select a cluster to see its member trends.</p>
                )}
                {selectedClusterId && clusterDetailLoading && (
                  <p className="text-sm text-gray-400 text-center py-16">Loading…</p>
                )}
                {selectedClusterId && !clusterDetailLoading && clusterDetail && (
                  <div className="space-y-4">
                    <div>
                      <h3 className="font-semibold text-gray-900">{clusterDetail.theme || "Cluster"}</h3>
                      {clusterDetail.summary && <p className="text-sm text-gray-500 mt-1">{clusterDetail.summary}</p>}
                    </div>
                    <div className="divide-y divide-gray-50 border border-gray-100 rounded-lg overflow-hidden max-h-[420px] overflow-y-auto">
                      {clusterDetail.trends.length === 0 && (
                        <p className="px-4 py-6 text-center text-xs text-gray-400">No trends linked yet.</p>
                      )}
                      {clusterDetail.trends.map((t) => (
                        <div key={t.id} className="flex items-center gap-3 px-4 py-3">
                          <PlatformBadge platform={t.platform} />
                          <span className="flex-1 text-sm text-gray-700 truncate">{t.title}</span>
                          <span className="text-xs text-gray-400 whitespace-nowrap">{fmt(t.collected_at)}</span>
                          {t.url && (
                            <a href={t.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:text-blue-800 shrink-0">
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Personas ── */}
          {page === "personas" && (
            <div className="grid lg:grid-cols-[1fr,1.1fr] gap-6 items-start lg:h-[calc(100vh-11rem)]">
              <div className="grid sm:grid-cols-2 gap-4 lg:h-full lg:content-start lg:overflow-y-auto lg:pr-1">
                {personas.length === 0 && (
                  <p className="text-gray-400 text-sm sm:col-span-2">No personas yet — run the pipeline first.</p>
                )}
                {personas.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => selectPersona(p.id)}
                    className={`text-left bg-white rounded-xl border p-6 space-y-3 transition-colors ${
                      selectedPersonaId === p.id ? "border-blue-300 ring-1 ring-blue-100" : "border-gray-100 hover:border-gray-200"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="font-semibold text-gray-900">{p.name}</h3>
                      <MomentumBadge momentum={p.momentum} />
                    </div>
                    <p className="text-sm text-gray-500 line-clamp-2">{p.description}</p>
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
                  </button>
                ))}
              </div>

              <div className="bg-white rounded-xl border border-gray-100 p-6 lg:h-full lg:overflow-y-auto">
                {!selectedPersonaId && (
                  <p className="text-sm text-gray-400 text-center py-16">Select a persona to see content ideas &amp; linked trends.</p>
                )}
                {selectedPersonaId && personaDetailLoading && (
                  <p className="text-sm text-gray-400 text-center py-16">Loading…</p>
                )}
                {selectedPersonaId && !personaDetailLoading && personaDetail && (
                  <div className="space-y-5">
                    <div>
                      <div className="flex items-start justify-between gap-3">
                        <h3 className="font-semibold text-gray-900">{personaDetail.name}</h3>
                        <MomentumBadge momentum={personaDetail.momentum} />
                      </div>
                      <p className="text-sm text-gray-500 mt-1">{personaDetail.description}</p>
                      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-xs text-gray-400">
                        {personaDetail.status && <span className="capitalize">{personaDetail.status}</span>}
                        {personaDetail.first_seen_at && <span>First seen {fmt(personaDetail.first_seen_at)}</span>}
                        {personaDetail.last_seen_at && <span>Last seen {fmt(personaDetail.last_seen_at)}</span>}
                      </div>
                    </div>

                    {personaOccurrences.length > 0 && (
                      <>
                        <div>
                          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
                            Occurrences by day of week
                          </p>
                          <WeekdayBarChart occurrences={personaOccurrences} dominantDay={null} />
                        </div>
                        <div>
                          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-4">Timeline</p>
                          <OccurrenceTimeline occurrences={personaOccurrences} />
                        </div>
                      </>
                    )}

                    {personaDetail.content_suggestions && personaDetail.content_suggestions.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1.5">
                          <Lightbulb className="h-3.5 w-3.5 text-amber-500" /> Content ideas
                        </p>
                        <div className="grid gap-2.5">
                          {personaDetail.content_suggestions.map((s, i) => (
                            <div key={i} className="rounded-lg border border-gray-100 p-3">
                              <div className="flex items-center justify-between gap-2">
                                <p className="text-sm font-medium text-gray-800 leading-snug">{s.title}</p>
                                <span className="shrink-0 text-xs text-gray-400">{s.format}</span>
                              </div>
                              {s.hook && <p className="text-xs text-gray-500 mt-1">{s.hook}</p>}
                              <p className="text-xs font-medium text-blue-600 mt-1">{s.platform}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {personaDetail.sample_trends && personaDetail.sample_trends.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Linked trends</p>
                        <div className="divide-y divide-gray-50 border border-gray-100 rounded-lg overflow-hidden">
                          {personaDetail.sample_trends.map((t) => (
                            <div key={t.id} className="flex items-center gap-3 px-4 py-3">
                              <PlatformBadge platform={t.platform} />
                              <span className="flex-1 text-sm text-gray-700 truncate">{t.title}</span>
                              {t.url && (
                                <a href={t.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:text-blue-800 shrink-0">
                                  <ExternalLink className="h-3.5 w-3.5" />
                                </a>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── History ── */}
          {page === "history" && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {PATTERN_ORDER.map((p) => (
                  <div key={p} className="bg-white rounded-xl border border-gray-100 p-4">
                    <p className="text-2xl font-bold text-gray-900">
                      {trendHistory.filter((t) => (t.recurrence_pattern ?? "unclear") === p).length}
                    </p>
                    <span className={`inline-flex mt-1.5 px-2 py-0.5 rounded text-xs font-semibold ${PATTERN_BADGE[p]}`}>
                      {PATTERN_LABEL[p]}
                    </span>
                  </div>
                ))}
              </div>

              <div className="grid lg:grid-cols-[1fr,1.2fr] gap-6 items-start lg:h-[calc(100vh-11rem)]">
                <div className="bg-white rounded-xl border border-gray-100 overflow-hidden lg:h-full lg:flex lg:flex-col">
                  <div className="px-6 py-4 border-b border-gray-50 flex items-center justify-between shrink-0">
                    <h2 className="font-semibold text-gray-900 text-sm">Trend themes</h2>
                    <span className="text-xs text-gray-400">{trendHistory.length} tracked</span>
                  </div>
                  <ul className="divide-y divide-gray-50 overflow-y-auto lg:flex-1">
                    {trendHistory.length === 0 && (
                      <li className="px-6 py-10 text-center text-sm text-gray-400">
                        No trend history yet — it accumulates as the daily pipeline runs.
                      </li>
                    )}
                    {trendHistory
                      .slice()
                      .sort((a, b) => (b.last_seen_at ?? "").localeCompare(a.last_seen_at ?? ""))
                      .map((theme) => (
                        <li key={theme.id}>
                          <button
                            onClick={() => selectTheme(theme.id)}
                            className={`w-full text-left px-6 py-3.5 transition-colors ${
                              selectedThemeId === theme.id ? "bg-blue-50" : "hover:bg-gray-50"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <p className="text-sm font-medium text-gray-900 truncate">{theme.canonical_name}</p>
                              <PatternBadge pattern={theme.recurrence_pattern} />
                            </div>
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1 text-xs text-gray-400">
                              <span>{theme.occurrence_count} occurrence{theme.occurrence_count !== 1 ? "s" : ""}</span>
                              <span>·</span>
                              <span>last seen {fmt(theme.last_seen_at)}</span>
                              {theme.recurrence_pattern === "weekly" && theme.dominant_day_of_week != null && (
                                <>
                                  <span>·</span>
                                  <span>usually {WEEKDAYS_FULL[theme.dominant_day_of_week]}</span>
                                </>
                              )}
                            </div>
                          </button>
                        </li>
                      ))}
                  </ul>
                </div>

                <div className="bg-white rounded-xl border border-gray-100 p-6 lg:h-full lg:overflow-y-auto">
                  {!selectedThemeId && (
                    <p className="text-sm text-gray-400 text-center py-16">Select a trend to see its history.</p>
                  )}
                  {selectedThemeId && occurrencesLoading && (
                    <p className="text-sm text-gray-400 text-center py-16">Loading…</p>
                  )}
                  {selectedThemeId && !occurrencesLoading && (() => {
                    const theme = trendHistory.find((t) => t.id === selectedThemeId);
                    if (!theme) return null;
                    return (
                      <div className="space-y-6">
                        <div>
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <h3 className="font-semibold text-gray-900">{theme.canonical_name}</h3>
                              {theme.description && <p className="text-sm text-gray-500 mt-1">{theme.description}</p>}
                            </div>
                            <PatternBadge pattern={theme.recurrence_pattern} />
                          </div>
                          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-xs text-gray-400">
                            <span>First seen {fmt(theme.first_seen_at)}</span>
                            <span>Last seen {fmt(theme.last_seen_at)}</span>
                            <span>{theme.occurrence_count} occurrences</span>
                            {theme.pattern_confidence != null && (
                              <span>{Math.round(theme.pattern_confidence * 100)}% confidence</span>
                            )}
                          </div>
                        </div>

                        <div>
                          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
                            Occurrences by day of week
                          </p>
                          <WeekdayBarChart occurrences={occurrences} dominantDay={theme.dominant_day_of_week} />
                        </div>

                        <div>
                          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-4">Timeline</p>
                          <OccurrenceTimeline occurrences={occurrences} />
                        </div>

                        <div>
                          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Occurrence log</p>
                          <div className="border border-gray-100 rounded-lg overflow-hidden max-h-56 overflow-y-auto">
                            <table className="w-full text-xs">
                              <thead className="bg-gray-50 sticky top-0">
                                <tr>
                                  <th className="text-left px-4 py-2 font-semibold text-gray-500">Date</th>
                                  <th className="text-left px-4 py-2 font-semibold text-gray-500">Day</th>
                                  <th className="text-left px-4 py-2 font-semibold text-gray-500">Size</th>
                                  <th className="text-left px-4 py-2 font-semibold text-gray-500">Durability</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-gray-50">
                                {occurrences
                                  .slice()
                                  .sort((a, b) => b.occurrence_date.localeCompare(a.occurrence_date))
                                  .map((o) => (
                                    <tr key={o.id}>
                                      <td className="px-4 py-2 text-gray-700 whitespace-nowrap">{o.occurrence_date}</td>
                                      <td className="px-4 py-2 text-gray-500">{WEEKDAYS[o.day_of_week]}</td>
                                      <td className="px-4 py-2 text-gray-500">{o.size ?? "—"}</td>
                                      <td className="px-4 py-2 text-gray-500 capitalize">{o.durability ?? "—"}</td>
                                    </tr>
                                  ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </div>
              </div>
            </div>
          )}

          {/* ── Users ── */}
          {page === "users" && (
            <div className="space-y-4">
              {/* Pending banner */}
              {userList.filter(u => !u.approved).length > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-3 flex items-center gap-2 text-sm text-amber-700">
                  <Clock className="h-4 w-4 shrink-0" />
                  {userList.filter(u => !u.approved).length} user{userList.filter(u => !u.approved).length !== 1 ? "s" : ""} waiting for approval
                </div>
              )}

              {userList.length === 0 && (
                <p className="text-gray-400 text-sm">No users yet.</p>
              )}

              {userList.map((u) => (
                <div key={u.user_id} className={`bg-white rounded-xl border overflow-hidden ${!u.approved ? "border-amber-200" : "border-gray-100"}`}>
                  {/* User header row */}
                  <div className="flex items-center gap-4 px-6 py-4 border-b border-gray-50 flex-wrap">
                    <span className="font-mono text-xs text-gray-400 shrink-0">{u.user_id.slice(0, 16)}…</span>

                    {/* Status badge */}
                    {u.approved ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs font-medium">
                        <CheckCircle className="h-3 w-3" /> Approved
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-100 text-amber-700 rounded text-xs font-medium">
                        <Clock className="h-3 w-3" /> Pending
                      </span>
                    )}

                    {/* Plan badge + toggle */}
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${u.plan === "pro" ? "bg-indigo-100 text-indigo-700" : "bg-gray-100 text-gray-500"}`}>
                      {u.plan === "pro" ? "Pro" : "Free"}
                    </span>
                    <span className="text-xs text-gray-400">{u.content_profiles.length} profile{u.content_profiles.length !== 1 ? "s" : ""}</span>
                    <span className="text-xs text-gray-400 ml-auto">{fmt(u.created_at)}</span>

                    {/* Actions */}
                    <div className="flex items-center gap-2">
                      {!u.approved ? (
                        <button
                          onClick={() => setApproval(u.user_id, true)}
                          disabled={approving === u.user_id}
                          className="inline-flex items-center gap-1 px-3 py-1 bg-green-600 text-white text-xs rounded-lg hover:bg-green-700 disabled:opacity-50 transition"
                        >
                          <CheckCircle className="h-3 w-3" />
                          {approving === u.user_id ? "…" : "Approve"}
                        </button>
                      ) : (
                        <button
                          onClick={() => setApproval(u.user_id, false)}
                          disabled={approving === u.user_id}
                          className="inline-flex items-center gap-1 px-3 py-1 border border-red-200 text-red-500 text-xs rounded-lg hover:bg-red-50 disabled:opacity-50 transition"
                        >
                          <XCircle className="h-3 w-3" />
                          {approving === u.user_id ? "…" : "Revoke"}
                        </button>
                      )}
                      {u.plan === "free" ? (
                        <button
                          onClick={() => setPlan(u.user_id, "pro")}
                          className="px-3 py-1 bg-indigo-600 text-white text-xs rounded-lg hover:bg-indigo-700 transition"
                        >
                          → Pro
                        </button>
                      ) : (
                        <button
                          onClick={() => setPlan(u.user_id, "free")}
                          className="px-3 py-1 border border-gray-200 text-gray-500 text-xs rounded-lg hover:bg-gray-50 transition"
                        >
                          → Free
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Content profiles */}
                  {u.content_profiles.length === 0 ? (
                    <p className="px-6 py-3 text-xs text-gray-400 italic">No content profiles yet</p>
                  ) : (
                    <div className="divide-y divide-gray-50">
                      {u.content_profiles.map((cp) => (
                        <div key={cp.id} className="flex items-center gap-3 px-6 py-3">
                          <div className={`h-2 w-2 rounded-full shrink-0 ${cp.is_active ? "bg-green-400" : "bg-gray-300"}`} />
                          <span className="text-sm font-medium text-gray-800 w-36 truncate">{cp.name}</span>
                          <span className="text-xs text-gray-500">{cp.industry_niche || <span className="italic text-gray-300">no niche</span>}</span>
                          <div className="flex gap-1 ml-2">
                            {cp.target_platforms.slice(0, 4).map((p) => (
                              <span key={p} className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-xs">{p}</span>
                            ))}
                          </div>
                          <span className="ml-auto text-xs text-gray-300">{fmt(cp.created_at)}</span>
                        </div>
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

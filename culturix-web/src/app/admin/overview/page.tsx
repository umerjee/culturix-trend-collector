"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { TrendingUp, Layers, Users, LayoutDashboard, AlertTriangle, Activity, RefreshCw, CalendarDays, Skull } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import type { AdminStats, Trend, Cluster, Digest, IntegrationHealthEntry, HighVelocityAlert, CalendarEventEntry, RunpodOrphanKillEntry } from "@/lib/admin/types";
import { fmt } from "@/lib/admin/types";
import { StatCard, PlatformBadge } from "@/components/admin/badges";
import Badge from "@/components/ui/Badge";
import ConfirmDialog from "@/components/ui/ConfirmDialog";

const HEALTH_VARIANT: Record<string, "success" | "warning" | "danger"> = {
  ok: "success", degraded: "warning", down: "danger",
};

// `fmt` from lib/admin/types always appends a time-of-day, which is
// misleading for date-only calendar events (they'd all show "12:00 AM").
function fmtDateOnly(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00Z");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

const EVENT_CATEGORY_STYLE: Record<string, string> = {
  holiday: "bg-emerald-50 text-emerald-700",
  religious: "bg-purple-50 text-purple-700",
  political: "bg-red-50 text-red-700",
  sports: "bg-blue-50 text-blue-700",
  music: "bg-pink-50 text-pink-700",
};

// Mirrors app/services/calendar_events.py's TRACKED_REGIONS — the fixed set
// of countries the trend collectors (and so this calendar) actually cover.
const EVENT_REGIONS = ["US", "GB", "IN", "JP", "KR", "FR", "DE", "BR", "CA", "AU", "CN", "IT", "ES", "PT"];

export default function OverviewPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [trends, setTrends] = useState<Trend[]>([]);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [digests, setDigests] = useState<Digest[]>([]);
  const [health, setHealth] = useState<IntegrationHealthEntry[]>([]);
  const [alerts, setAlerts] = useState<HighVelocityAlert[]>([]);
  const [events, setEvents] = useState<CalendarEventEntry[]>([]);
  const [eventCategoryFilter, setEventCategoryFilter] = useState<string>("");
  const [eventRegionFilter, setEventRegionFilter] = useState<string>("");
  const [orphanKills, setOrphanKills] = useState<RunpodOrphanKillEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [checkingHealth, setCheckingHealth] = useState(false);
  const [confirmCheckOpen, setConfirmCheckOpen] = useState(false);
  const [healthCheckError, setHealthCheckError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    const results = await Promise.allSettled([
      fetchAdminData<AdminStats>("stats"),
      fetchAdminData<Trend[]>("trends", { limit: 8 }),
      fetchAdminData<Cluster[]>("clusters", { limit: 6 }),
      fetchAdminData<Digest[]>("digests", { limit: 5 }),
      fetchAdminData<IntegrationHealthEntry[]>("integration-health"),
      fetchAdminData<HighVelocityAlert[]>("high-velocity-alerts", { limit: 5 }),
      fetchAdminData<CalendarEventEntry[]>("calendar-events", { limit: 120 }),
      fetchAdminData<RunpodOrphanKillEntry[]>("runpod-orphan-kills", { limit: 20 }),
    ]);
    const [s, t, c, d, h, a, ev, ok] = results;
    const firstErr = results.find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
    if (firstErr) setError(firstErr.reason?.message ?? String(firstErr.reason));
    setStats(s.status === "fulfilled" ? s.value : null);
    setTrends(t.status === "fulfilled" && Array.isArray(t.value) ? t.value : []);
    setClusters(c.status === "fulfilled" && Array.isArray(c.value) ? c.value : []);
    setDigests(d.status === "fulfilled" && Array.isArray(d.value) ? d.value : []);
    setHealth(h.status === "fulfilled" && Array.isArray(h.value) ? h.value : []);
    setAlerts(a.status === "fulfilled" && Array.isArray(a.value) ? a.value : []);
    setEvents(ev.status === "fulfilled" && Array.isArray(ev.value) ? ev.value : []);
    setOrphanKills(ok.status === "fulfilled" && Array.isArray(ok.value) ? ok.value : []);
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  async function runHealthCheckNow() {
    setCheckingHealth(true);
    setHealthCheckError(null);
    try {
      const res = await fetch("/api/admin/integration-health/check-now", { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setHealthCheckError(data.detail ?? `Health check failed (${res.status})`);
        return;
      }
      const h = await fetchAdminData<IntegrationHealthEntry[]>("integration-health");
      setHealth(h);
    } catch (err) {
      setHealthCheckError(err instanceof Error ? err.message : "Network error — check your connection and try again.");
    } finally {
      setCheckingHealth(false);
      setConfirmCheckOpen(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-gray-400 text-center py-16">Loading admin data…</p>;
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-bold text-gray-900 text-xl">Overview</h1>
        <p className="text-xs text-gray-400">Cultural intelligence at a glance</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-5 py-3 text-sm text-red-700 font-mono break-all">
          ⚠ {error}
        </div>
      )}

      {/* Should normally be empty — a non-empty result means the RunPod
          orphan-pod reaper (app/scheduler.py, every 30 min) caught a pod
          left running past ORPHAN_POD_MAX_AGE_HOURS and auto-terminated
          it. Surfaced prominently since real money is on the line — added
          2026-09-16 after a manually-created eval pod ran unterminated
          for ~5.5h with nothing catching it. */}
      {orphanKills.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-amber-100">
            <h2 className="font-semibold text-amber-800 text-sm flex items-center gap-1.5">
              <Skull className="h-4 w-4" /> RunPod pods auto-terminated (orphan-pod reaper)
            </h2>
          </div>
          <ul className="divide-y divide-amber-100">
            {orphanKills.map((k) => (
              <li key={k.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                <span className="flex-1 text-amber-900 truncate">
                  {k.pod_name ?? k.pod_id} {k.gpu_display_name && <span className="text-amber-600">({k.gpu_display_name})</span>}
                </span>
                <span className="text-xs text-amber-700 whitespace-nowrap shrink-0">
                  ran {k.age_hours.toFixed(1)}h{k.estimated_cost != null ? ` — ~$${k.estimated_cost.toFixed(2)}` : ""}
                </span>
                <span className="text-xs text-amber-600 whitespace-nowrap shrink-0">{fmt(k.killed_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Stat cards — now backed directly by GET /admin/stats instead of
          recomputing counts from already-fetched lists. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={<TrendingUp className="h-5 w-5" />} value={stats?.total_trends ?? 0} label="Trends collected" />
        <StatCard icon={<Layers className="h-5 w-5" />} value={stats?.total_clusters ?? 0} label="Clusters" />
        <StatCard icon={<Users className="h-5 w-5" />} value={stats?.total_personas ?? 0} label="Personas" />
        <StatCard icon={<LayoutDashboard className="h-5 w-5" />} value={Object.keys(stats?.by_platform ?? {}).length} label="Platforms" />
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-50">
            <h2 className="font-semibold text-gray-900 text-sm">Recent Trends</h2>
            <Link href="/admin/trends" className="text-xs text-primary-600 hover:underline">View all →</Link>
          </div>
          <ul className="divide-y divide-gray-50">
            {trends.map((t) => (
              <li key={t.id} className="flex items-center gap-3 px-6 py-3">
                <PlatformBadge platform={t.platform} />
                <span className="flex-1 text-sm text-gray-700 truncate">{t.content}</span>
                <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">{fmt(t.collected_at)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-50">
            <h2 className="font-semibold text-gray-900 text-sm">Top Clusters</h2>
            <Link href="/admin/clusters" className="text-xs text-primary-600 hover:underline">View all →</Link>
          </div>
          {clusters.length === 0 && <p className="text-sm text-gray-400 px-6 py-8">No clusters yet — run the pipeline.</p>}
          <ul className="divide-y divide-gray-50">
            {clusters.map((c) => (
              <li key={c.id} className="px-6 py-4">
                <div className="flex items-start justify-between gap-4">
                  <p className="flex-1 min-w-0 font-semibold text-sm text-gray-900">{c.description || `Cluster ${c.label}`}</p>
                  <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">{c.trend_count ?? 0} trends</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Integration health — previously invisible in the UI despite being
          checked daily by the scheduler (app/integration_health.py). */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-50">
          <h2 className="font-semibold text-gray-900 text-sm flex items-center gap-1.5">
            <Activity className="h-4 w-4 text-gray-400" /> Integration health
          </h2>
          <button
            onClick={() => setConfirmCheckOpen(true)}
            disabled={checkingHealth}
            className="text-xs text-gray-500 hover:text-gray-700 inline-flex items-center gap-1 disabled:opacity-50"
          >
            <RefreshCw className="h-3 w-3" /> {checkingHealth ? "Checking…" : "Check now"}
          </button>
        </div>
        {healthCheckError && (
          <p className="text-sm text-red-600 px-6 py-2 border-b border-gray-50">{healthCheckError}</p>
        )}
        {health.length === 0 ? (
          <p className="text-sm text-gray-400 px-6 py-8">No health checks recorded yet.</p>
        ) : (
          <ul className="divide-y divide-gray-50">
            {health.map((h) => (
              <li key={h.integration} className="flex items-center gap-3 px-6 py-3">
                <span className="flex-1 text-sm text-gray-700 capitalize">{h.integration.replace(/_/g, " ")}</span>
                {h.error && <span className="text-xs text-gray-400 truncate max-w-xs">{h.error}</span>}
                <Badge variant={HEALTH_VARIANT[h.status] ?? "neutral"} className="capitalize shrink-0">{h.status}</Badge>
                <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">{fmt(h.checked_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Upcoming events — holidays/religious/political (live since 2026-09-07)
          plus sports/music (added 2026-09-16); previously had no admin view
          at all despite already feeding content_strategist.py's prompts.
          Category/region filtering is client-side over the already-fetched
          120-day window (dozens-to-low-hundreds of rows) rather than a
          refetch per filter change — simpler and instant. */}
      {events.length > 0 && (() => {
        const filteredEvents = events.filter((e) =>
          (!eventCategoryFilter || e.category === eventCategoryFilter) &&
          (!eventRegionFilter || e.regions.length === 0 || e.regions.includes(eventRegionFilter))
        );
        return (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-50 flex items-center justify-between gap-3 flex-wrap">
              <h2 className="font-semibold text-gray-900 text-sm flex items-center gap-1.5">
                <CalendarDays className="h-4 w-4 text-indigo-500" /> Upcoming events
              </h2>
              <div className="flex items-center gap-2">
                <select
                  value={eventCategoryFilter}
                  onChange={(e) => setEventCategoryFilter(e.target.value)}
                  className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-600 bg-white"
                >
                  <option value="">All categories</option>
                  {Object.keys(EVENT_CATEGORY_STYLE).map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <select
                  value={eventRegionFilter}
                  onChange={(e) => setEventRegionFilter(e.target.value)}
                  className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-600 bg-white"
                >
                  <option value="">All regions</option>
                  {EVENT_REGIONS.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
            </div>
            {filteredEvents.length === 0 ? (
              <p className="px-6 py-6 text-sm text-gray-400">No events match this filter.</p>
            ) : (
              <ul className="divide-y divide-gray-50 max-h-96 overflow-y-auto">
                {filteredEvents.map((e) => (
                  <li key={e.id} className="flex items-center gap-3 px-6 py-3">
                    <span className={`text-[10px] font-medium uppercase tracking-wide px-2 py-0.5 rounded shrink-0 ${EVENT_CATEGORY_STYLE[e.category] ?? "bg-gray-100 text-gray-600"}`}>
                      {e.category}
                    </span>
                    <span className="flex-1 text-sm text-gray-700 truncate" title={e.description ?? undefined}>{e.name}</span>
                    <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">
                      {e.regions.length > 0 ? e.regions.join(", ") : "global"}
                    </span>
                    <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">{fmtDateOnly(e.date)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })()}

      {/* High-velocity alerts — same visibility gap as integration health. */}
      {alerts.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-50">
            <h2 className="font-semibold text-gray-900 text-sm flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4 text-amber-500" /> High-velocity alerts
            </h2>
          </div>
          <ul className="divide-y divide-gray-50">
            {alerts.map((a) => (
              <li key={a.id} className="flex items-center gap-3 px-6 py-3">
                <PlatformBadge platform={a.platform} />
                <span className="flex-1 text-sm text-gray-700 truncate">{a.description ?? a.external_id}</span>
                <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">
                  {/* velocity_score is likes/hour averaged over the post's whole
                      lifetime, not a "Nx faster than normal" multiplier — the
                      old "Nx velocity" label implied a ratio that was never
                      being computed. */}
                  {a.velocity_score != null ? `${a.velocity_score.toFixed(1)} likes/hr` : "—"}
                </span>
                <span className="text-xs text-gray-400 whitespace-nowrap shrink-0" title="When the post was actually made, not when it was scraped">
                  posted {fmt(a.trend_posted_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {digests.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-50">
            <h2 className="font-semibold text-gray-900 text-sm">Recent Digests</h2>
          </div>
          <div className="divide-y divide-gray-50">
            {digests.map((d) => (
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

      <ConfirmDialog
        open={confirmCheckOpen}
        title="Run integration health checks now?"
        description="Hits the live edge-tts, Twitter proxy, and Google Trends endpoints directly instead of waiting for the daily scheduled check."
        confirmLabel="Check now"
        loading={checkingHealth}
        onConfirm={runHealthCheckNow}
        onCancel={() => setConfirmCheckOpen(false)}
      />
    </div>
  );
}

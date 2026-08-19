"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { TrendingUp, Layers, Users, LayoutDashboard, AlertTriangle, Activity, RefreshCw } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import type { AdminStats, Trend, Cluster, Digest, IntegrationHealthEntry, HighVelocityAlert } from "@/lib/admin/types";
import { fmt } from "@/lib/admin/types";
import { StatCard, PlatformBadge } from "@/components/admin/badges";
import Badge from "@/components/ui/Badge";
import ConfirmDialog from "@/components/ui/ConfirmDialog";

const HEALTH_VARIANT: Record<string, "success" | "warning" | "danger"> = {
  ok: "success", degraded: "warning", down: "danger",
};

export default function OverviewPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [trends, setTrends] = useState<Trend[]>([]);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [digests, setDigests] = useState<Digest[]>([]);
  const [health, setHealth] = useState<IntegrationHealthEntry[]>([]);
  const [alerts, setAlerts] = useState<HighVelocityAlert[]>([]);
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
    ]);
    const [s, t, c, d, h, a] = results;
    const firstErr = results.find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
    if (firstErr) setError(firstErr.reason?.message ?? String(firstErr.reason));
    setStats(s.status === "fulfilled" ? s.value : null);
    setTrends(t.status === "fulfilled" && Array.isArray(t.value) ? t.value : []);
    setClusters(c.status === "fulfilled" && Array.isArray(c.value) ? c.value : []);
    setDigests(d.status === "fulfilled" && Array.isArray(d.value) ? d.value : []);
    setHealth(h.status === "fulfilled" && Array.isArray(h.value) ? h.value : []);
    setAlerts(a.status === "fulfilled" && Array.isArray(a.value) ? a.value : []);
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
                  {a.velocity_score != null ? `${a.velocity_score.toFixed(1)}x velocity` : "—"}
                </span>
                <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">{fmt(a.received_at)}</span>
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

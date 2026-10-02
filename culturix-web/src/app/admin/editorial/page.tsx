"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import EditorialCandidateCard, { type Candidate, type Meta } from "@/components/admin/EditorialCandidateCard";
import { validateMetrics, type FieldErrors, type MetricsForm } from "@/lib/editorial/validate";

type Coverage = { by_continent: Record<string, number>; gaps: string[] };
type ListResponse = Meta & { candidates: Candidate[]; blocked: Candidate[]; coverage: Coverage; rank_weights_version: number };
type PerfRow = {
  post_id: string; platform: string; post_url: string; region: string; continent: string; language: string;
  format: string | null; trend_title: string; source_title: string; hook: string | null; tone: string | null;
  duration_seconds: number | null; views: number | null; likes: number | null; comments: number | null;
  shares: number | null; saves: number | null; follows: number | null; avg_watch_seconds: number | null;
  completion_rate: number | null; comments_per_1k: number | null; shares_per_1k: number | null;
  saves_per_1k: number | null; follows_per_1k: number | null; last_fetched_at: string | null;
};
type PerfGroup = { value: string; posts: number; views: number; comments_per_1k: number | null; shares_per_1k: number | null; enough_data: boolean };
type Performance = { rows: PerfRow[]; groups: Record<string, PerfGroup[]>; min_posts_for_comparison: number };

const FILTERS = [
  { value: "", label: "Open" }, { value: "candidate", label: "To review" }, { value: "scripted", label: "Scripted" },
  { value: "approved", label: "Approved" }, { value: "published", label: "Published" }, { value: "blocked", label: "Blocked" },
];

export default function EditorialPage() {
  const [filter, setFilter] = useState("");
  const [data, setData] = useState<ListResponse | null>(null);
  const [perf, setPerf] = useState<Performance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, performance] = await Promise.all([
        fetchAdminData<ListResponse>("editorial-candidates"),
        fetchAdminData<Performance>("editorial-performance"),
      ]);
      setData(list);
      setPerf(performance);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function findCandidates() {
    setRefreshing(true);
    setRefreshNote(null);
    try {
      const res = await fetch("/api/admin/editorial/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ days: 7 }) });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(out.detail || `HTTP ${res.status}`);
      const skipped = (out.skipped_regions || []).length;
      setRefreshNote(`${out.created} new candidate${out.created === 1 ? "" : "s"}${out.blocked ? `, ${out.blocked} blocked by the safety screen` : ""}${skipped ? `; ${skipped} countries skipped (no recent trends or no usable sources)` : ""}.`);
      await load();
    } catch (e) {
      setRefreshNote(`Could not find candidates: ${String((e as Error).message)}`);
    } finally {
      setRefreshing(false);
    }
  }

  const replace = (updated: Candidate) => setData((d) => d && ({
    ...d,
    candidates: d.candidates.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)),
    blocked: d.blocked.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)),
  }));

  const all = data ? [...data.candidates, ...data.blocked] : [];
  const visible = all.filter((c) => (filter ? c.status === filter : c.status !== "blocked" && c.status !== "rejected"));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-xl font-semibold text-gray-900">Trend editorial</h1>
          <p className="mt-1 text-sm text-gray-600">
            Pairs a current trend in a country with a sourced detail from that country&apos;s history or culture.
            Facts can only come from the source; safety and fact-checks must pass before anything is rendered or posted.
          </p>
        </div>
        <button type="button" onClick={findCandidates} disabled={refreshing}
          className="inline-flex min-h-[40px] items-center gap-2 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-50">
          {refreshing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
          Find new candidates
        </button>
      </div>
      {refreshNote && <p role="status" className="text-sm text-gray-700">{refreshNote}</p>}

      {data && (
        <section aria-label="Coverage" className="rounded-xl border border-gray-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-gray-900">Coverage of open candidates</h2>
          <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-2 text-sm">
            {Object.entries(data.coverage.by_continent).filter(([k, v]) => v > 0 || ["Asia", "Americas", "Africa", "Europe"].includes(k)).map(([k, v]) => (
              <div key={k} className="flex items-baseline gap-1.5"><dt className="text-gray-600">{k}</dt><dd className={`font-semibold tabular-nums ${v ? "text-gray-900" : "text-red-600"}`}>{v}</dd></div>
            ))}
          </dl>
          {data.coverage.gaps.length > 0 && (
            <p className="mt-2 text-xs text-red-700">
              Nothing open for {data.coverage.gaps.join(", ")}. Ingest sources for those countries in the Source library, or check that their trends are being collected.
            </p>
          )}
        </section>
      )}

      <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button key={f.value} type="button" aria-pressed={filter === f.value} onClick={() => setFilter(f.value)}
            className={`min-h-[36px] rounded-full border px-3 text-sm ${filter === f.value ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50"}`}>
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-gray-500"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading…</p>
      ) : error ? (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          Could not load the editorial workflow: {error}
          <button type="button" onClick={load} className="ml-3 font-semibold underline">Retry</button>
        </div>
      ) : visible.length === 0 ? (
        <p className="rounded-xl border border-dashed border-gray-200 p-6 text-center text-sm text-gray-500">
          {filter ? "Nothing with this status." : "No open candidates. Use “Find new candidates” to build some from the last week of trends."}
        </p>
      ) : (
        <div className="space-y-4">
          {visible.map((c) => <EditorialCandidateCard key={c.id} candidate={c} meta={data!} onChange={replace} />)}
        </div>
      )}

      {perf && <PerformanceSection perf={perf} onUpdated={load} />}
    </div>
  );
}

const EMPTY_METRICS: MetricsForm = { views: "", likes: "", comments: "", shares: "", saves: "", follows: "", avgWatchSeconds: "", completionRate: "" };
const GROUP_LABEL: Record<string, string> = { continent: "Continent", format: "Format", platform: "Platform", language: "Language" };

function rate(value: number | null) {
  return value == null ? "–" : value.toFixed(1);
}

function PerformanceSection({ perf, onUpdated }: { perf: Performance; onUpdated: () => void }) {
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<MetricsForm>(EMPTY_METRICS);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [message, setMessage] = useState<string | null>(null);

  async function save(postId: string) {
    const { errors: found, payload } = validateMetrics(form, false);
    setErrors(found);
    if (Object.keys(found).length) return;
    const res = await fetch(`/api/admin/editorial/posts/${postId}/metrics`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const out = await res.json().catch(() => ({}));
    if (!res.ok) return setMessage(`Could not save: ${out.detail || res.status}`);
    setMessage("Metrics updated.");
    setEditing(null);
    setForm(EMPTY_METRICS);
    onUpdated();
  }

  return (
    <section aria-labelledby="perf-heading" className="rounded-xl border border-gray-200 bg-white p-4 sm:p-5">
      <h2 id="perf-heading" className="text-base font-semibold text-gray-900">Posted videos and what we can learn</h2>
      <p className="mt-1 text-sm text-gray-600">
        Rates are per 1,000 views. A group with fewer than {perf.min_posts_for_comparison} posts is a hint, not a result,
        and even larger groups only show what happened, not why.
      </p>
      {message && <p role="status" className="mt-2 text-xs text-gray-700">{message}</p>}

      {perf.rows.length === 0 ? (
        <p className="mt-4 text-sm text-gray-500">No posts recorded yet. Record one from an approved candidate.</p>
      ) : (
        <>
          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {Object.entries(perf.groups).map(([dimension, groups]) => (
              <div key={dimension}>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">{GROUP_LABEL[dimension] || dimension}</h3>
                <table className="mt-1 w-full text-left text-xs">
                  <thead className="text-gray-500"><tr><th className="py-1 font-medium">Value</th><th className="py-1 font-medium">Posts</th><th className="py-1 font-medium">Comments/1k</th><th className="py-1 font-medium">Shares/1k</th></tr></thead>
                  <tbody>
                    {groups.map((g) => (
                      <tr key={g.value} className={`border-t border-gray-100 ${g.enough_data ? "" : "text-gray-400"}`}>
                        <td className="py-1">{g.value.replace(/_/g, " ")}</td><td className="py-1 tabular-nums">{g.posts}</td>
                        <td className="py-1 tabular-nums">{rate(g.comments_per_1k)}</td><td className="py-1 tabular-nums">{rate(g.shares_per_1k)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>

          <div className="mt-6 overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-xs">
              <thead className="text-gray-500">
                <tr>{["Post", "Place", "Format", "Hook", "Views", "Comments/1k", "Shares/1k", "Saves/1k", "Follows/1k", "Avg watch", ""].map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {perf.rows.map((r) => (
                  <tr key={r.post_id} className="border-t border-gray-100 align-top">
                    <td className="py-2 pr-3"><a href={r.post_url} target="_blank" rel="noopener noreferrer" className="font-medium text-indigo-700 hover:underline">{r.platform}</a><div className="text-gray-400">{r.language}</div></td>
                    <td className="py-2 pr-3">{r.region} · {r.continent}</td>
                    <td className="py-2 pr-3">{(r.format || "–").replace(/_/g, " ")}<div className="text-gray-400">{r.tone}{r.duration_seconds ? ` · ${r.duration_seconds}s` : ""}</div></td>
                    <td className="py-2 pr-3 max-w-[220px]">{r.hook}<div className="text-gray-400">{r.source_title}</div></td>
                    <td className="py-2 pr-3 tabular-nums">{r.views ?? "–"}</td>
                    <td className="py-2 pr-3 tabular-nums">{rate(r.comments_per_1k)}</td>
                    <td className="py-2 pr-3 tabular-nums">{rate(r.shares_per_1k)}</td>
                    <td className="py-2 pr-3 tabular-nums">{rate(r.saves_per_1k)}</td>
                    <td className="py-2 pr-3 tabular-nums">{rate(r.follows_per_1k)}</td>
                    <td className="py-2 pr-3 tabular-nums">{r.avg_watch_seconds != null ? `${r.avg_watch_seconds}s` : "–"}</td>
                    <td className="py-2">
                      {editing === r.post_id ? (
                        <div className="grid w-64 grid-cols-2 gap-1">
                          {(Object.keys(EMPTY_METRICS) as (keyof MetricsForm)[]).map((k) => (
                            <label key={k} className="text-[11px] text-gray-500">{k.replace(/([A-Z])/g, " $1").toLowerCase()}
                              <input value={form[k]} onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} inputMode="decimal" className="mt-0.5 w-full rounded border border-gray-200 px-1.5 py-1 text-xs" />
                              {errors[k] && <span className="block text-red-600">{errors[k]}</span>}
                            </label>
                          ))}
                          {errors.form && <p className="col-span-2 text-red-600">{errors.form}</p>}
                          <button type="button" onClick={() => save(r.post_id)} className="col-span-1 rounded bg-gray-900 px-2 py-1.5 text-white">Save</button>
                          <button type="button" onClick={() => setEditing(null)} className="col-span-1 rounded border border-gray-200 px-2 py-1.5">Cancel</button>
                        </div>
                      ) : (
                        <button type="button" onClick={() => { setEditing(r.post_id); setForm(EMPTY_METRICS); setErrors({}); }} className="font-medium text-indigo-700 hover:underline">Update numbers</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

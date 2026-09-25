"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, EyeOff, Film, Loader2, Play, RefreshCw, Archive, Upload, Search } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import { CATEGORY_LABELS } from "@/lib/worldTypes";
import WorldScriptReview, { ScoreChip, type Review } from "@/components/admin/WorldScriptReview";
import WorldVideoPrompt from "@/components/admin/WorldVideoPrompt";
import WorldNarrationEditor, { FixClaimsButton, type NarrationLine } from "@/components/admin/WorldNarrationEditor";

type Grounding = { grounded: boolean | null; unsupported_claims: string[]; judge_failed: boolean };
type Draft = {
  id: string; title: string | null; status: string; final_video_url: string | null;
  subject_region: string | null; subject_category: string | null; duration_seconds: number | null; shot_count: number;
  hook_line: string | null; narration: string[]; narration_lines: NarrationLine[]; grounding: Grounding | null; craft_score: number | null; has_host: boolean;
  source_type: string | null; source_url: string | null; render_estimate: { gpu_seconds: number; cost_usd: number } | null;
  generation_error: string | null; publish_recommended: boolean | null; published: boolean; created_at: string | null;
  previous_video_urls: string[]; visual_style: string | null; raw_video_url: string | null; review: Review | null;
};

const STATUS_LABEL: Record<string, string> = { scripting: "Under production", idea: "Script ready", animating: "Rendering", ready: "Rendered", failed: "Render failed", posted: "Posted" };

const STYLE_LABEL: Record<string, string> = { illustrated_history: "Illustrated", graphic_novel: "Graphic novel" };

// A draft's "ready" status splits into two very different states a curator cares about
// separately (needs a publish decision vs. already live) — the status filter below treats
// them as distinct options even though the backend stores one status value for both.
const STATUS_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "scripting", label: "Under production" },
  { value: "idea", label: "Script ready" },
  { value: "animating", label: "Rendering" },
  { value: "ready_unpublished", label: "Rendered, awaiting publish" },
  { value: "published", label: "Published" },
  { value: "failed", label: "Render failed" },
  { value: "posted", label: "Posted" },
];

function matchesStatusFilter(draft: Draft, filter: string): boolean {
  if (!filter) return true;
  if (filter === "published") return draft.status === "ready" && draft.published;
  if (filter === "ready_unpublished") return draft.status === "ready" && !draft.published;
  return draft.status === filter;
}

type SortMode = "newest" | "score" | "cost_asc" | "cost_desc" | "title";

function sortDrafts(drafts: Draft[], sortBy: SortMode): Draft[] {
  if (sortBy === "newest") return drafts; // API already returns newest first
  const sorted = [...drafts];
  if (sortBy === "score") sorted.sort((a, b) => (b.review?.score ?? -1) - (a.review?.score ?? -1));
  else if (sortBy === "cost_asc") sorted.sort((a, b) => (a.render_estimate?.cost_usd ?? Infinity) - (b.render_estimate?.cost_usd ?? Infinity));
  else if (sortBy === "cost_desc") sorted.sort((a, b) => (b.render_estimate?.cost_usd ?? -Infinity) - (a.render_estimate?.cost_usd ?? -Infinity));
  else if (sortBy === "title") sorted.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
  return sorted;
}

function formatDay(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
}

function formatDayTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
}

// "Version 2 of 5" for drafts that share a title, oldest first, counting live and archived drafts together.
function versionLabels(drafts: Draft[]): Record<string, string> {
  const byTitle: Record<string, Draft[]> = {};
  for (const draft of drafts) (byTitle[draft.title || "Untitled"] ||= []).push(draft);
  const labels: Record<string, string> = {};
  for (const group of Object.values(byTitle)) {
    if (group.length < 2) continue;
    group.sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
    group.forEach((draft, index) => { labels[draft.id] = `Version ${index + 1} of ${group.length}`; });
  }
  return labels;
}

// Every take of a draft, oldest first: earlier takes were archived when a re-render replaced them.
function TakeLinks({ draft }: { draft: Draft }) {
  const current = draft.final_video_url || draft.raw_video_url;
  const takes = [...(draft.previous_video_urls || []), ...(current && !(draft.previous_video_urls || []).includes(current) ? [current] : [])];
  if (takes.length === 0) return null;
  return <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
    {takes.map((url, index) => <a key={url} href={url} target="_blank" rel="noreferrer" className="inline-flex min-h-8 items-center text-primary-600 hover:underline">{takes.length === 1 ? "Watch video" : `Take ${index + 1}${index === takes.length - 1 ? " (latest)" : ""}`}</a>)}
  </span>;
}

function statusLabel(draft: Draft): string {
  if (draft.status === "ready") return draft.published ? "Published" : "Rendered, awaiting publish";
  return STATUS_LABEL[draft.status] || draft.status;
}

export default function WorldProductionPage() {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [archived, setArchived] = useState<Draft[]>([]);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [regionFilter, setRegionFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortMode>("newest");

  function load() {
    setLoading(true);
    fetchAdminData<Draft[]>("world-production").then(setDrafts).catch(() => setDrafts([])).finally(() => setLoading(false));
    fetchAdminData<Draft[]>("world-production-archived").then(setArchived).catch(() => setArchived([]));
  }
  useEffect(() => { load(); }, []);
  const versions = versionLabels([...drafts, ...archived]);

  const categoryOptions = useMemo(
    () => Array.from(new Set(drafts.map((d) => d.subject_category || "custom"))).sort(),
    [drafts],
  );
  const regionOptions = useMemo(
    () => Array.from(new Set(drafts.map((d) => d.subject_region || "global"))).sort(),
    [drafts],
  );
  const visibleDrafts = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = drafts.filter((d) => {
      if (categoryFilter && (d.subject_category || "custom") !== categoryFilter) return false;
      if (regionFilter && (d.subject_region || "global") !== regionFilter) return false;
      if (!matchesStatusFilter(d, statusFilter)) return false;
      if (q && !(d.title || "").toLowerCase().includes(q) && !(d.hook_line || "").toLowerCase().includes(q)) return false;
      return true;
    });
    return sortDrafts(filtered, sortBy);
  }, [drafts, categoryFilter, regionFilter, statusFilter, search, sortBy]);
  const hasActiveFilters = Boolean(categoryFilter || regionFilter || statusFilter || search);
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const d of drafts) {
      const key = d.status === "ready" ? (d.published ? "published" : "ready_unpublished") : d.status;
      counts[key] = (counts[key] || 0) + 1;
    }
    return counts;
  }, [drafts]);

  useEffect(() => {
    if (!drafts.some((draft) => draft.status === "animating" || draft.status === "scripting")) return;
    const timer = setInterval(load, drafts.some((draft) => draft.status === "scripting") ? 6000 : 20000);
    return () => clearInterval(timer);
  }, [drafts]);

  async function generateVideo(draft: Draft) {
    const cost = draft.render_estimate ? ` (about $${draft.render_estimate.cost_usd.toFixed(2)} of GPU time, more if a worker has to cold-start or a segment is retried)` : "";
    if (!window.confirm(`Render "${draft.title}" as a ${draft.duration_seconds}s video${cost}? This starts a paid GPU job.

Open "What will be generated" on the card first to see the exact prompts and narration.`)) return;
    const res = await fetch(`/api/admin/world-production/${draft.id}/generate-video`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    setMessage(res.ok ? "Render started. This page refreshes automatically; it usually takes several minutes." : (data.detail || "Video generation could not be started."));
    load();
  }

  async function publish(draft: Draft) {
    if (!window.confirm(`Publish "${draft.title}" to the public World page? Anyone will be able to watch it.`)) return;
    const res = await fetch(`/api/admin/world-production/${draft.id}/publish`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    setMessage(res.ok ? "Published. It is now live on the World page." : (data.detail || "Could not publish."));
    load();
  }

  async function unpublish(draft: Draft) {
    if (!window.confirm(`Take "${draft.title}" off the public World page? The video is kept and can be published again.`)) return;
    const res = await fetch(`/api/admin/world-production/${draft.id}/unpublish`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    setMessage(res.ok ? "Unpublished. The video is kept." : (data.detail || "Could not unpublish."));
    load();
  }

  async function archive(draft: Draft) {
    if (!window.confirm(`Archive "${draft.title}"? It leaves this list and the public page, and the subject can be regenerated from the Subject Library.`)) return;
    const res = await fetch(`/api/admin/world-production/${draft.id}/archive`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    setMessage(res.ok ? "Archived." : (data.detail || "Could not archive."));
    load();
  }

  return <div className="max-w-6xl">
    <div className="mb-6 sm:mb-8 flex flex-wrap items-start justify-between gap-3 sm:gap-4"><div><div className="flex items-center gap-2 text-primary-600 text-xs font-bold uppercase tracking-wider"><Film className="h-4 w-4" /> World production</div><h1 className="mt-2 text-2xl font-bold text-gray-900">World video drafts</h1><p className="mt-1 text-sm text-gray-500">Review each fact-checked script, then start the render. A finished render stays private until you publish it.</p></div><div className="flex items-center gap-2"><Link href="/admin/curated-items" className="inline-flex items-center gap-2 rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-sm font-semibold text-primary-700 hover:bg-primary-100">+ New subject</Link><button onClick={load} className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-700"><RefreshCw className="h-4 w-4" /> Refresh</button></div></div>
    {message && <p className="mb-5 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700">{message}</p>}

    {drafts.length > 0 && <>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
        {STATUS_FILTER_OPTIONS.filter((opt) => opt.value && statusCounts[opt.value]).map((opt) => (
          <button key={opt.value} onClick={() => {
            // A status chip's count is always the TRUE total for that status, unfiltered by
            // category/region/search — but clicking it used to only set statusFilter, so a
            // leftover category filter from a moment ago could silently AND against it and
            // show "0 of 22 drafts" even though the chip just said e.g. "2 Rendering".
            // Confirmed live: exactly this, right after filtering to Species then clicking
            // Rendering. A status chip is a strong, standalone "show me this" click, not
            // meant to combine with whatever was left over — so it resets the rest.
            const next = statusFilter === opt.value ? "" : opt.value;
            setStatusFilter(next);
            setCategoryFilter("");
            setRegionFilter("");
            setSearch("");
          }}
            className={`rounded-full px-2.5 py-1 font-semibold ${statusFilter === opt.value ? "bg-primary-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}>
            {statusCounts[opt.value]} {opt.label}
          </button>
        ))}
      </div>
      <div className="mb-5 flex flex-wrap items-center gap-2 rounded-xl border border-gray-100 bg-white p-3">
        <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Browse</span>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search title..."
            className="w-44 rounded-lg border border-gray-200 bg-white py-2 pl-8 pr-3 text-sm text-gray-700" aria-label="Search by title" />
        </div>
        <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700" aria-label="Filter by category">
          <option value="">All categories</option>
          {categoryOptions.map((cat) => <option key={cat} value={cat}>{CATEGORY_LABELS[cat] || cat}</option>)}
        </select>
        <select value={regionFilter} onChange={(e) => setRegionFilter(e.target.value)} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700" aria-label="Filter by region">
          <option value="">All regions</option>
          {regionOptions.map((r) => <option key={r} value={r}>{r === "global" ? "Global" : r}</option>)}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700" aria-label="Filter by status">
          {STATUS_FILTER_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
        </select>
        <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortMode)} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700" aria-label="Sort by">
          <option value="newest">Newest first</option>
          <option value="score">Highest script score</option>
          <option value="cost_asc">Cheapest to render</option>
          <option value="cost_desc">Most expensive to render</option>
          <option value="title">Title A-Z</option>
        </select>
        {hasActiveFilters && <button onClick={() => { setCategoryFilter(""); setRegionFilter(""); setStatusFilter(""); setSearch(""); }} className="px-2 py-2 text-xs font-medium text-primary-600 hover:text-primary-800">Clear filters</button>}
        <span className="ml-auto text-xs text-gray-400">{visibleDrafts.length} of {drafts.length} drafts</span>
      </div>
    </>}

    {loading && drafts.length === 0 ? <p className="text-sm text-gray-400">Loading World drafts...</p> : drafts.length === 0 ? <p className="rounded-xl border border-dashed border-gray-200 p-8 text-sm text-gray-400">No World drafts yet. Select a subject in the Subject Library first.</p> : visibleDrafts.length === 0 ? <p className="rounded-xl border border-dashed border-gray-200 p-8 text-sm text-gray-400">No drafts match these filters.</p> : <div className="space-y-3">{visibleDrafts.map((draft) => {
      const unsupported = draft.grounding?.unsupported_claims?.length ?? 0;
      if (draft.status === "scripting") return <article key={draft.id} aria-busy="true" className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-4 sm:p-5">
        <div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase text-gray-400"><span>{draft.subject_region || "global"}</span><span>{draft.subject_category || "subject"}</span><span className="inline-flex items-center gap-1 text-amber-600"><Loader2 className="h-3 w-3 animate-spin" /> Under production</span></div>
        <h2 className="mt-1 text-lg font-semibold text-gray-500">{draft.title || "Untitled World subject"}</h2>
        <p className="mt-1 text-sm text-gray-500">Writing the script and checking every claim against its source. This takes a minute or two, and this card fills in by itself when it is done.</p>
        <div className="mt-4 space-y-2" aria-hidden="true"><div className="h-3 w-3/4 animate-pulse rounded bg-gray-200" /><div className="h-3 w-5/6 animate-pulse rounded bg-gray-200" /><div className="h-3 w-2/3 animate-pulse rounded bg-gray-200" /></div>
      </article>;
      const noScript = draft.shot_count === 0;
      return <article key={draft.id} className="rounded-xl border border-gray-100 bg-white p-4 sm:p-5 shadow-sm">
        <div className="flex flex-wrap sm:flex-nowrap items-start justify-between gap-2 sm:gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase text-gray-400"><span>{draft.subject_region || "global"}</span><span>{draft.subject_category || "subject"}</span><span className={draft.published ? "text-emerald-600" : draft.status === "ready" ? "text-amber-600" : ""}>{statusLabel(draft)}</span>{draft.has_host && <span>with host</span>}{draft.visual_style && <span>{STYLE_LABEL[draft.visual_style] || draft.visual_style}</span>}</div>
            <h2 className="mt-1 text-lg font-semibold text-gray-900">{draft.title || "Untitled World subject"}{versions[draft.id] && <span className="ml-2 align-middle rounded bg-gray-100 px-1.5 py-0.5 text-[11px] font-semibold text-gray-600">{versions[draft.id]}</span>}</h2>
            {draft.hook_line && <p className="mt-1 text-sm text-gray-600">{draft.hook_line}</p>}
          </div>
          <div className="shrink-0 text-right text-sm text-gray-500">{draft.duration_seconds || "-"}s · {draft.shot_count} shots{draft.render_estimate && <span className="block text-xs text-gray-400">~${draft.render_estimate.cost_usd.toFixed(2)} to render</span>}</div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
          {draft.grounding?.grounded === true && <span className="inline-flex items-center gap-1 text-green-700"><CheckCircle2 className="h-3.5 w-3.5" /> Fact-checked against source</span>}
          {draft.grounding?.grounded === false && <span className="inline-flex flex-wrap items-center gap-2 text-amber-700"><span className="inline-flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5" /> {unsupported} claim{unsupported === 1 ? "" : "s"} not backed by the source</span>{(draft.status === "idea" || draft.status === "failed") && !noScript && <FixClaimsButton draftId={draft.id} onChanged={load} onMessage={setMessage} />}</span>}
          {(!draft.grounding || draft.grounding.grounded === null) && <span className="text-gray-400">Fact-check unavailable</span>}
          {draft.review?.era?.label && <span className="text-gray-500">Period: {draft.review.era.label}</span>}
          {draft.source_url && <a href={draft.source_url} target="_blank" rel="noreferrer" className="text-primary-600 hover:underline">Source: {draft.source_type}</a>}
          {draft.status !== "animating" && <ScoreChip review={draft.review} />}
          {draft.narration.length > 0 && <button onClick={() => setOpen(open === draft.id ? null : draft.id)} className="text-gray-500 hover:text-gray-800">{open === draft.id ? "Hide narration" : "Read narration"}</button>}
        </div>
        {open === draft.id && <div className="mt-3 rounded-lg bg-gray-50 p-3 text-sm text-gray-700">
          <WorldNarrationEditor key={`${draft.id}-${(draft.narration_lines || []).map((l) => l.dialogue).join("|")}-${draft.hook_line}`} draftId={draft.id} hook={draft.hook_line}
            lines={draft.narration_lines || []} claims={draft.grounding?.unsupported_claims || []}
            editable={draft.status === "idea" || draft.status === "failed"} onChanged={load} onMessage={setMessage} />
          {unsupported > 0 && <div className="mt-3 border-t border-amber-200 pt-2 text-xs text-amber-800"><p className="font-semibold">Not found in the source:</p><ul className="list-disc pl-5">{draft.grounding!.unsupported_claims.map((claim, index) => <li key={index}>{claim}</li>)}</ul></div>}
        </div>}
        {(draft.status === "idea" || draft.status === "failed") && <>
          <WorldScriptReview draftId={draft.id} review={draft.review} editable onChanged={load} onMessage={setMessage} />
          <WorldVideoPrompt draftId={draft.id} />
        </>}
        {(draft.status === "ready" || draft.status === "posted") && draft.review && <WorldScriptReview draftId={draft.id} review={draft.review} editable={false} onChanged={load} onMessage={setMessage} />}
        {draft.generation_error && draft.status === "failed" && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{draft.generation_error}{noScript && " Archive this draft, then generate the subject again from the Subject Library."}</p>}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {(draft.final_video_url || (draft.previous_video_urls || []).length > 0) && <TakeLinks draft={draft} />}
          {draft.status === "ready" && !draft.published && <button onClick={() => publish(draft)} className="inline-flex min-h-10 items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white"><Upload className="h-3.5 w-3.5" /> Publish</button>}
          {draft.status === "ready" && draft.published && <button onClick={() => unpublish(draft)} className="inline-flex min-h-10 items-center gap-1 rounded-md border border-gray-200 px-3 py-1.5 text-xs font-semibold text-gray-700"><EyeOff className="h-3.5 w-3.5" /> Unpublish</button>}
          {draft.status === "ready" && !draft.published && draft.publish_recommended === false && <span className="text-xs text-amber-700">Automatic QA did not recommend publishing this render.</span>}
          {!draft.final_video_url && !noScript && <button disabled={draft.status === "animating"} onClick={() => generateVideo(draft)} className="inline-flex min-h-10 items-center gap-1 rounded-md bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"><Play className="h-3.5 w-3.5" /> {draft.status === "failed" ? "Retry render" : "Generate video"}</button>}
          <span className="text-xs text-gray-400">{draft.status === "animating" ? "Rendering in progress" : ""}</span>
          <button disabled={draft.status === "animating"} onClick={() => archive(draft)} className="ml-auto inline-flex min-h-10 items-center gap-1 rounded-md bg-gray-100 px-2.5 py-1.5 text-xs font-semibold text-gray-600 disabled:opacity-50"><Archive className="h-3.5 w-3.5" /> Archive</button>
        </div>
      </article>;
    })}</div>}

    {archived.length > 0 && <details className="mt-10 rounded-xl border border-gray-100 bg-white p-4 sm:p-5">
      <summary className="cursor-pointer text-sm font-semibold text-gray-700">Archived videos ({archived.length})</summary>
      <p className="mt-2 text-xs text-gray-400">Retired drafts keep their rendered video. Nothing here is public.</p>
      <ul className="mt-3 divide-y divide-gray-100">
        {archived.map((draft) => <li key={draft.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3">
          <div className="min-w-0">
            <p className="text-sm font-medium text-gray-800">{draft.title || "Untitled"}{versions[draft.id] && <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-[11px] font-semibold text-gray-600">{versions[draft.id]}</span>}</p>
            <p className="text-[11px] uppercase text-gray-400">{[draft.subject_region, draft.visual_style ? (STYLE_LABEL[draft.visual_style] || draft.visual_style) : "Photoreal", draft.duration_seconds ? `${draft.duration_seconds}s` : null, draft.shot_count ? `${draft.shot_count} scenes` : null, formatDayTime(draft.created_at)].filter(Boolean).join(" · ")}</p>
            {draft.narration?.[0] && <p className="mt-0.5 max-w-xl text-xs italic text-gray-500 [overflow-wrap:anywhere]">“{draft.narration[0]}”</p>}
          </div>
          <TakeLinks draft={draft} />
        </li>)}
      </ul>
    </details>}
  </div>;
}

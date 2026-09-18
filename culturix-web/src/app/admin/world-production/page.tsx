"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Film, Play, RefreshCw, Archive } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";

type Grounding = { grounded: boolean | null; unsupported_claims: string[]; judge_failed: boolean };
type Draft = {
  id: string; title: string | null; status: string; final_video_url: string | null;
  subject_region: string | null; subject_category: string | null; duration_seconds: number | null; shot_count: number;
  hook_line: string | null; narration: string[]; grounding: Grounding | null; craft_score: number | null; has_host: boolean;
  source_type: string | null; source_url: string | null; render_estimate: { gpu_seconds: number; cost_usd: number } | null;
  generation_error: string | null; publish_recommended: boolean | null; created_at: string | null;
};

const STATUS_LABEL: Record<string, string> = { idea: "Script ready", animating: "Rendering", ready: "Published", failed: "Render failed", posted: "Posted" };

export default function WorldProductionPage() {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);

  function load() { setLoading(true); fetchAdminData<Draft[]>("world-production").then(setDrafts).catch(() => setDrafts([])).finally(() => setLoading(false)); }
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!drafts.some((draft) => draft.status === "animating")) return;
    const timer = setInterval(load, 20000);
    return () => clearInterval(timer);
  }, [drafts]);

  async function generateVideo(draft: Draft) {
    const cost = draft.render_estimate ? ` (about $${draft.render_estimate.cost_usd.toFixed(2)} of GPU time)` : "";
    if (!window.confirm(`Render "${draft.title}" as a ${draft.duration_seconds}s video${cost}? This starts a paid GPU job.`)) return;
    const res = await fetch(`/api/admin/world-production/${draft.id}/generate-video`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    setMessage(res.ok ? "Render started. This page refreshes automatically; it usually takes several minutes." : (data.detail || "Video generation could not be started."));
    load();
  }

  async function archive(draft: Draft) {
    const verb = draft.status === "ready" ? "Unpublish and archive" : "Archive";
    if (!window.confirm(`${verb} "${draft.title}"? The subject can then be regenerated from the Subject Library.`)) return;
    const res = await fetch(`/api/admin/world-production/${draft.id}/unpublish`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    setMessage(res.ok ? "Archived." : (data.detail || "Could not archive."));
    load();
  }

  return <div className="max-w-6xl">
    <div className="mb-8 flex items-start justify-between gap-4"><div><div className="flex items-center gap-2 text-primary-600 text-xs font-bold uppercase tracking-wider"><Film className="h-4 w-4" /> World production</div><h1 className="mt-2 text-2xl font-bold text-gray-900">World video drafts</h1><p className="mt-1 text-sm text-gray-500">Review each fact-checked script, then start the render. A finished render publishes to the public World page straight away; archive it to take it down.</p></div><button onClick={load} className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-700"><RefreshCw className="h-4 w-4" /> Refresh</button></div>
    {message && <p className="mb-5 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700">{message}</p>}
    {loading && drafts.length === 0 ? <p className="text-sm text-gray-400">Loading World drafts...</p> : drafts.length === 0 ? <p className="rounded-xl border border-dashed border-gray-200 p-8 text-sm text-gray-400">No World drafts yet. Select a subject in the Subject Library first.</p> : <div className="space-y-3">{drafts.map((draft) => {
      const unsupported = draft.grounding?.unsupported_claims?.length ?? 0;
      return <article key={draft.id} className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase text-gray-400"><span>{draft.subject_region || "global"}</span><span>{draft.subject_category || "subject"}</span><span>{STATUS_LABEL[draft.status] || draft.status}</span>{draft.has_host && <span>with host</span>}</div>
            <h2 className="mt-1 text-lg font-semibold text-gray-900">{draft.title || "Untitled World subject"}</h2>
            {draft.hook_line && <p className="mt-1 text-sm text-gray-600">{draft.hook_line}</p>}
          </div>
          <div className="shrink-0 text-right text-sm text-gray-500">{draft.duration_seconds || "-"}s · {draft.shot_count} shots{draft.render_estimate && <span className="block text-xs text-gray-400">~${draft.render_estimate.cost_usd.toFixed(2)} to render</span>}</div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
          {draft.grounding?.grounded === true && <span className="inline-flex items-center gap-1 text-green-700"><CheckCircle2 className="h-3.5 w-3.5" /> Fact-checked against source</span>}
          {draft.grounding?.grounded === false && <span className="inline-flex items-center gap-1 text-amber-700"><AlertTriangle className="h-3.5 w-3.5" /> {unsupported} claim{unsupported === 1 ? "" : "s"} not backed by the source</span>}
          {(!draft.grounding || draft.grounding.grounded === null) && <span className="text-gray-400">Fact-check unavailable</span>}
          {draft.source_url && <a href={draft.source_url} target="_blank" rel="noreferrer" className="text-primary-600 hover:underline">Source: {draft.source_type}</a>}
          {draft.narration.length > 0 && <button onClick={() => setOpen(open === draft.id ? null : draft.id)} className="text-gray-500 hover:text-gray-800">{open === draft.id ? "Hide narration" : "Read narration"}</button>}
        </div>
        {open === draft.id && <div className="mt-3 rounded-lg bg-gray-50 p-3 text-sm text-gray-700">
          <ol className="list-decimal space-y-1 pl-5">{draft.narration.map((line, index) => <li key={index}>{line}</li>)}</ol>
          {unsupported > 0 && <div className="mt-3 border-t border-amber-200 pt-2 text-xs text-amber-800"><p className="font-semibold">Not found in the source:</p><ul className="list-disc pl-5">{draft.grounding!.unsupported_claims.map((claim, index) => <li key={index}>{claim}</li>)}</ul></div>}
        </div>}
        {draft.generation_error && draft.status === "failed" && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{draft.generation_error}</p>}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {draft.final_video_url && <a href={draft.final_video_url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-primary-600 hover:underline">Watch video</a>}
          {draft.status === "ready" && draft.publish_recommended === false && <span className="text-xs text-amber-700">Automatic QA did not recommend publishing this render.</span>}
          {!draft.final_video_url && <button disabled={draft.status === "animating"} onClick={() => generateVideo(draft)} className="inline-flex items-center gap-1 rounded-md bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"><Play className="h-3.5 w-3.5" /> {draft.status === "failed" ? "Retry render" : "Generate video"}</button>}
          <span className="text-xs text-gray-400">{draft.status === "animating" ? "Rendering in progress" : ""}</span>
          <button disabled={draft.status === "animating"} onClick={() => archive(draft)} className="ml-auto inline-flex items-center gap-1 rounded-md bg-gray-100 px-2.5 py-1.5 text-xs font-semibold text-gray-600 disabled:opacity-50"><Archive className="h-3.5 w-3.5" /> {draft.status === "ready" ? "Unpublish" : "Archive"}</button>
        </div>
      </article>;
    })}</div>}
  </div>;
}

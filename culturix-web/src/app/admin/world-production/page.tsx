"use client";

import { useEffect, useState } from "react";
import { Film, Play, RefreshCw } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";

type Draft = { id: string; title: string | null; status: string; final_video_url: string | null; subject_region: string | null; subject_category: string | null; duration_seconds: number | null; shot_count: number; created_at: string | null };

export default function WorldProductionPage() {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  function load() { setLoading(true); fetchAdminData<Draft[]>("world-production").then(setDrafts).catch(() => setDrafts([])).finally(() => setLoading(false)); }
  useEffect(() => { load(); }, []);

  async function generateVideo(id: string) {
    setMessage("Video generation started. This may take several minutes.");
    const res = await fetch(`/api/admin/world-production/${id}/generate-video`, { method: "POST" });
    if (!res.ok) setMessage("Video generation could not be started.");
    load();
  }

  return <div className="max-w-6xl">
    <div className="mb-8 flex items-start justify-between gap-4"><div><div className="flex items-center gap-2 text-primary-600 text-xs font-bold uppercase tracking-wider"><Film className="h-4 w-4" /> World production</div><h1 className="mt-2 text-2xl font-bold text-gray-900">World video drafts</h1><p className="mt-1 text-sm text-gray-500">Review AI-planned subject videos and start rendering when the draft is ready.</p></div><button onClick={load} className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-700"><RefreshCw className="h-4 w-4" /> Refresh</button></div>
    {message && <p className="mb-5 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700">{message}</p>}
    {loading ? <p className="text-sm text-gray-400">Loading World drafts...</p> : drafts.length === 0 ? <p className="rounded-xl border border-dashed border-gray-200 p-8 text-sm text-gray-400">No World drafts yet. Select a subject in the Subject Library first.</p> : <div className="space-y-3">{drafts.map((draft) => <article key={draft.id} className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-4"><div><div className="flex gap-2 text-[11px] font-semibold uppercase text-gray-400"><span>{draft.subject_region || "global"}</span><span>{draft.subject_category || "subject"}</span><span>{draft.status}</span></div><h2 className="mt-1 text-lg font-semibold text-gray-900">{draft.title || "Untitled World subject"}</h2></div><span className="text-sm text-gray-500">{draft.duration_seconds || "-"}s · {draft.shot_count} shots</span></div><div className="mt-4 flex items-center gap-2">{draft.final_video_url ? <a href={draft.final_video_url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-primary-600 hover:underline">Watch video</a> : <button disabled={draft.status === "animating"} onClick={() => generateVideo(draft.id)} className="inline-flex items-center gap-1 rounded-md bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"><Play className="h-3.5 w-3.5" /> Generate video</button>}<span className="text-xs text-gray-400">{draft.status === "animating" ? "Rendering in progress" : "Subject remains the focus; host is optional"}</span></div></article>)}</div>}
  </div>;
}
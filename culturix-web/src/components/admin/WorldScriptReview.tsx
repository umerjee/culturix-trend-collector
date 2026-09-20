"use client";

import { useState } from "react";
import { ChevronDown, Loader2, Sparkles } from "lucide-react";
import WorldPeriodEditor, { type Phase } from "@/components/admin/WorldPeriodEditor";

export type ReviewDimension = { score: number | null; weight: number; note: string };
export type ReviewSuggestion = { shot: number | null; dimension: string | null; issue: string; fix: string };
export type Review = {
  score: number | null; passes_bar: boolean | null; feedback: string | null; judge_failed: boolean;
  dimensions: Record<string, ReviewDimension>; suggestions: ReviewSuggestion[];
  auto_improved?: boolean; first_score?: number | null;
  anachronisms?: string[]; era?: { label: string; start_year: number; end_year: number; phases?: Phase[] } | null;
};

const DIMENSION_LABEL: Record<string, string> = {
  hook: "Hook", story: "Story", dynamism: "Movement and action", narration: "Narration", visuals: "Pictures match the words", accuracy: "Accuracy",
};

function tone(score: number | null): { bar: string; text: string } {
  if (score === null) return { bar: "bg-gray-300", text: "text-gray-500" };
  if (score >= 75) return { bar: "bg-emerald-500", text: "text-emerald-700" };
  if (score >= 55) return { bar: "bg-amber-500", text: "text-amber-700" };
  return { bar: "bg-red-500", text: "text-red-700" };
}

export function ScoreChip({ review }: { review: Review | null }) {
  if (!review || review.score === null) return <span className="text-gray-400">Script not scored</span>;
  const { text } = tone(review.score);
  return <span className={`font-semibold ${text}`}>Script score {review.score}/100{review.passes_bar ? " · passes the bar" : ""}</span>;
}

export default function WorldScriptReview({ draftId, review, editable, onChanged, onMessage }: {
  draftId: string; review: Review | null; editable: boolean; onChanged: () => void; onMessage: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"improve" | "score" | null>(null);

  async function call(path: "improve" | "review", body?: object) {
    setBusy(path === "improve" ? "improve" : "score");
    try {
      const res = await fetch(`/api/admin/world-production/${draftId}/${path}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { onMessage(data.detail || "That did not work."); return; }
      if (path === "improve") {
        onMessage(data.improved ? `Script improved: ${data.score_before ?? "?"} to ${data.score_after ?? "?"} out of 100.` : data.message);
        if (data.improved) setNote("");
      } else onMessage(`Script scored ${data.score ?? "?"} out of 100.`);
      onChanged();
    } finally { setBusy(null); }
  }

  const dimensions = review ? Object.entries(review.dimensions).filter(([, d]) => d.score !== null || d.note) : [];

  return <section className="mt-3 rounded-lg border border-gray-100">
    <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex min-h-11 w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm">
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1"><span className="font-semibold text-gray-700">Script review</span><span className="text-xs"><ScoreChip review={review} /></span>
        {review?.auto_improved && review.first_score != null && <span className="text-xs text-gray-400">improved automatically from {review.first_score}</span>}</span>
      <ChevronDown className={`h-4 w-4 shrink-0 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} />
    </button>
    {open && <div className="border-t border-gray-100 px-3 py-3 text-sm">
      {!review ? <div>
        <p className="text-gray-500">This script was written before scoring existed. Score it to see where it is weak and what to change.</p>
        {editable && <button disabled={busy !== null} onClick={() => call("review")} className="mt-3 inline-flex min-h-10 items-center gap-1.5 rounded-md bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">{busy === "score" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} Score this script</button>}
      </div> : <div className="space-y-4">
        {review.judge_failed && <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">The AI reviewer was unavailable, so only the measured parts are shown. Try again in a moment.</p>}
        {review.era?.label && <p className="text-xs text-gray-500">Set in <span className="font-medium text-gray-700">{review.era.label}</span>. Only things from that period may appear.</p>}
        {!review.era && <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">No period was set for this video, so nothing checks it for out-of-period objects. Score it again to set one.</p>}
        {review.anachronisms && review.anachronisms.length > 0 && <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">Not from this period: {review.anachronisms.join(", ")}. Use Improve with AI to remove {review.anachronisms.length === 1 ? "it" : "them"}.</p>}
        {review.feedback && <p className="text-gray-700">{review.feedback}</p>}
        {review.era?.phases && review.era.phases.length > 0 && <WorldPeriodEditor key={JSON.stringify(review.era.phases)} draftId={draftId} phases={review.era.phases} editable={editable} onChanged={onChanged} onMessage={onMessage} />}
        <ul className="space-y-2.5">{dimensions.map(([key, d]) => <li key={key}>
          <div className="flex items-baseline justify-between gap-3 text-xs"><span className="font-medium text-gray-700">{DIMENSION_LABEL[key] || key}</span><span className={`tabular-nums font-semibold ${tone(d.score).text}`}>{d.score ?? "n/a"}</span></div>
          <div role="img" aria-label={`${DIMENSION_LABEL[key] || key}: ${d.score ?? "not scored"} out of 100`} className="mt-1 h-1.5 overflow-hidden rounded-full bg-gray-100"><div className={`h-full rounded-full ${tone(d.score).bar}`} style={{ width: `${d.score ?? 0}%` }} /></div>
          {d.note && <p className="mt-1 text-xs text-gray-500 [overflow-wrap:anywhere]">{d.note}</p>}
        </li>)}</ul>
        {review.suggestions.length > 0 && <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">What to improve</p>
          <ol className="mt-2 space-y-2">{review.suggestions.map((s, i) => <li key={i} className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-700 [overflow-wrap:anywhere]">
            <span className="font-semibold text-gray-900">{s.shot ? `Shot ${s.shot}` : "Whole video"}{s.dimension ? ` · ${DIMENSION_LABEL[s.dimension] || s.dimension}` : ""}</span>
            <span className="block">{s.issue}</span><span className="block text-primary-700">Fix: {s.fix}</span>
          </li>)}</ol>
        </div>}
        {editable ? <div className="rounded-md border border-gray-100 p-3">
          <label htmlFor={`note-${draftId}`} className="text-xs font-semibold text-gray-600">Anything specific to change? (optional)</label>
          <textarea id={`note-${draftId}`} value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={400} placeholder="For example: make the ending bigger, show more ships"
            className="mt-1 w-full rounded-md border border-gray-200 px-2.5 py-2 text-sm placeholder:text-gray-300 focus:border-primary-500 focus:outline-none" />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button disabled={busy !== null} onClick={() => call("improve", { note: note.trim() || null })} className="inline-flex min-h-10 items-center gap-1.5 rounded-md bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">{busy === "improve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} {busy === "improve" ? "Improving..." : "Improve with AI"}</button>
            <button disabled={busy !== null} onClick={() => call("review")} className="inline-flex min-h-10 items-center rounded-md border border-gray-200 px-3 py-1.5 text-xs font-semibold text-gray-600 disabled:opacity-50">{busy === "score" ? "Scoring..." : "Score again"}</button>
            <span className="text-xs text-gray-400">The rewrite only replaces the script if it scores higher and stays fact-checked.</span>
          </div>
        </div> : <p className="text-xs text-gray-400">The script can only be changed before the video is rendered.</p>}
      </div>}
    </div>}
  </section>;
}

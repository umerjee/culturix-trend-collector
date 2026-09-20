"use client";

import { useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";

type Segment = {
  index: number; shot_numbers: number[]; seconds: number; mode: string; prompt: string; negative_prompt: string;
  image_strength: number | null; opening_frame: { kind: string; url: string | null; name: string | null };
};
type Preview = {
  duration_seconds: number; look: string; estimate: { gpu_seconds: number; cost_usd: number }; segments: Segment[];
  narration: null | {
    voice: string | null; language: string; error: string | null; shot_seconds: number[];
    lines: { shot: number; text: string; starts_at: number; speech_seconds: number }[];
    mix: null | { ambient_volume: number; loudness_lufs: number };
  };
};

const OPENING_LABEL: Record<string, string> = {
  reference_photo: "Real reference photo", blank_canvas: "Plain dark canvas (no photo)", character_portrait: "Character portrait",
  previous_segment_last_frame: "Last frame of the previous segment", cast_portraits: "Cast portraits",
};

function shotsLabel(numbers: number[]): string {
  return numbers.length === 1 ? `shot ${numbers[0]}` : `shots ${numbers[0]}-${numbers[numbers.length - 1]}`;
}

export default function WorldVideoPrompt({ draftId }: { draftId: string }) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/admin/world-production/${draftId}/video-prompt`, { cache: "no-store" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setError(data.detail || "Could not build the preview."); setPreview(null); } else setPreview(data);
    } finally { setLoading(false); }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !preview && !loading) load();
  }

  return <section className="mt-3 rounded-lg border border-gray-100">
    <button onClick={toggle} aria-expanded={open} className="flex min-h-11 w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm">
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1"><span className="font-semibold text-gray-700">What will be generated</span><span className="text-xs text-gray-400">the exact prompts and narration, before any paid render</span></span>
      <ChevronDown className={`h-4 w-4 shrink-0 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} />
    </button>
    {open && <div className="border-t border-gray-100 px-3 py-3 text-sm">
      {loading && <p className="flex items-center gap-2 text-gray-500"><Loader2 className="h-4 w-4 animate-spin" /> Preparing the narration and prompts...</p>}
      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
      {preview && <div className="space-y-4">
        <p className="text-xs text-gray-500">{preview.duration_seconds}s · {preview.look} · about ${preview.estimate.cost_usd.toFixed(2)} of GPU time · {preview.segments.length} video segment{preview.segments.length === 1 ? "" : "s"}. Built by the same code the renderer uses, so nothing here is a guess.</p>
        {preview.narration && (preview.narration.error
          ? <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{preview.narration.error}</p>
          : <div className="rounded-md bg-gray-50 px-3 py-2.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Narration</p>
            <p className="mt-1 text-xs text-gray-600">One voice, {preview.narration.voice}, over the whole video. The video model adds ambient sound only, at {Math.round((preview.narration.mix?.ambient_volume ?? 0) * 100)}% volume, and the final mix is levelled to {preview.narration.mix?.loudness_lufs} LUFS.</p>
            <ol className="mt-2 space-y-1">{preview.narration.lines.map((line) => <li key={line.shot} className="text-xs text-gray-700 [overflow-wrap:anywhere]"><span className="tabular-nums text-gray-400">{line.starts_at.toFixed(1)}s</span> · shot {line.shot}: {line.text}</li>)}</ol>
          </div>)}
        <ol className="space-y-3">{preview.segments.map((seg) => <li key={seg.index} className="rounded-md border border-gray-100 p-3">
          <p className="text-xs font-semibold text-gray-700">Segment {seg.index} · {shotsLabel(seg.shot_numbers)} · {seg.seconds}s</p>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row">
            {seg.opening_frame.url && <a href={seg.opening_frame.url} target="_blank" rel="noreferrer" className="shrink-0 sm:w-40">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={seg.opening_frame.url} alt={seg.opening_frame.name || "Opening frame"} loading="lazy" className="h-28 w-full rounded-md object-cover sm:h-24 sm:w-40" />
            </a>}
            <div className="min-w-0 flex-1">
              <p className="text-xs text-gray-500">Opens on: <span className="font-medium text-gray-700">{OPENING_LABEL[seg.opening_frame.kind] || seg.opening_frame.kind}{seg.opening_frame.name ? ` (${seg.opening_frame.name})` : ""}</span>{seg.image_strength !== null && ` · held at ${seg.image_strength} so it can move`}</p>
              <p className="mt-2 whitespace-pre-wrap rounded-md bg-gray-900 px-3 py-2 font-mono text-[11px] leading-relaxed text-gray-100 [overflow-wrap:anywhere]">{seg.prompt}</p>
            </div>
          </div>
          <details className="mt-2"><summary className="cursor-pointer text-xs text-gray-400">Things the model is told to avoid</summary><p className="mt-1 text-xs text-gray-500 [overflow-wrap:anywhere]">{seg.negative_prompt}</p></details>
        </li>)}</ol>
        <button onClick={load} disabled={loading} className="min-h-10 rounded-md border border-gray-200 px-3 py-1.5 text-xs font-semibold text-gray-600 disabled:opacity-50">Refresh preview</button>
      </div>}
    </div>}
  </section>;
}

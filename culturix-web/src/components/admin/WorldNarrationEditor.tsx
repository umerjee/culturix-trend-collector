"use client";

import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

export type NarrationLine = { shot_number: number; dialogue: string };

const MAX_WORDS = 22;
const wordCount = (text: string) => text.trim().split(/\s+/).filter(Boolean).length;

// Removes claims the source does not back: the AI rewrites only the lines that hold them, and re-checks.
export function FixClaimsButton({ draftId, onChanged, onMessage }: { draftId: string; onChanged: () => void; onMessage: (message: string) => void }) {
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      const res = await fetch(`/api/admin/world-production/${draftId}/fix-claims`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      onMessage(res.ok ? data.message : (data.detail || "Could not fix the claims."));
      onChanged();
    } finally { setBusy(false); }
  }
  return <button disabled={busy} onClick={run} className="inline-flex min-h-9 items-center gap-1.5 rounded-md bg-amber-600 px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-60">
    {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} {busy ? "Fixing..." : "Fix with AI"}
  </button>;
}

// The narration a curator can correct by hand when the AI cannot. Saving re-runs the fact-check and the score.
export default function WorldNarrationEditor({ draftId, hook, lines, claims, editable, onChanged, onMessage }: {
  draftId: string; hook: string | null; lines: NarrationLine[]; claims: string[]; editable: boolean;
  onChanged: () => void; onMessage: (message: string) => void;
}) {
  const [hookText, setHookText] = useState(hook || "");
  const [texts, setTexts] = useState<Record<number, string>>(() => Object.fromEntries(lines.map((line) => [line.shot_number, line.dialogue])));
  const [busy, setBusy] = useState(false);
  const flagged = (text: string) => claims.some((claim) => claim.trim() !== "" && (text.includes(claim.trim()) || claim.includes(text.trim())));
  const changed = hookText.trim() !== (hook || "").trim() || lines.some((line) => (texts[line.shot_number] ?? "").trim() !== line.dialogue.trim());
  const tooLong = lines.some((line) => wordCount(texts[line.shot_number] ?? "") > MAX_WORDS);

  async function save() {
    setBusy(true);
    try {
      const res = await fetch(`/api/admin/world-production/${draftId}/edit-script`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hook_line: hookText, lines: lines.filter((l) => (texts[l.shot_number] ?? "").trim() !== l.dialogue.trim()).map((l) => ({ shot_number: l.shot_number, dialogue: texts[l.shot_number] })) }),
      });
      const data = await res.json().catch(() => ({}));
      onMessage(res.ok ? data.message : (data.detail || "Could not save."));
      onChanged();
    } finally { setBusy(false); }
  }

  if (!editable) return <ol className="list-decimal space-y-1 pl-5">{lines.map((line) => <li key={line.shot_number} className={flagged(line.dialogue) ? "text-amber-800" : ""}>{line.dialogue}</li>)}</ol>;

  return <div className="space-y-3">
    <div>
      <label htmlFor={`hook-${draftId}`} className="text-xs font-semibold text-gray-500">Headline (shown on the card and public page)</label>
      <textarea id={`hook-${draftId}`} value={hookText} onChange={(e) => setHookText(e.target.value)} rows={2} maxLength={300}
        className={`mt-1 w-full rounded-md border px-2.5 py-2 text-sm focus:outline-none focus:border-primary-500 ${flagged(hookText) ? "border-amber-400 bg-amber-50" : "border-gray-200 bg-white"}`} />
    </div>
    {lines.map((line) => {
      const text = texts[line.shot_number] ?? "";
      const words = wordCount(text);
      return <div key={line.shot_number}>
        <label htmlFor={`line-${draftId}-${line.shot_number}`} className="flex items-baseline justify-between text-xs font-semibold text-gray-500">
          <span>Shot {line.shot_number}{flagged(line.dialogue) ? " · not backed by the source" : ""}</span>
          <span className={`tabular-nums font-normal ${words > MAX_WORDS ? "text-red-600" : "text-gray-400"}`}>{words}/{MAX_WORDS} words</span>
        </label>
        <textarea id={`line-${draftId}-${line.shot_number}`} value={text} onChange={(e) => setTexts({ ...texts, [line.shot_number]: e.target.value })} rows={2}
          className={`mt-1 w-full rounded-md border px-2.5 py-2 text-sm focus:outline-none focus:border-primary-500 ${flagged(line.dialogue) ? "border-amber-400 bg-amber-50" : "border-gray-200 bg-white"}`} />
      </div>;
    })}
    <div className="flex flex-wrap items-center gap-2">
      <button disabled={busy || !changed || tooLong} onClick={save} className="inline-flex min-h-10 items-center gap-1.5 rounded-md bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} {busy ? "Saving and checking..." : "Save and re-check"}</button>
      <span className="text-xs text-gray-400">Saving re-runs the fact-check against the source and the script score.</span>
    </div>
  </div>;
}

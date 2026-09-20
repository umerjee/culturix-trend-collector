"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

export type Phase = { from_year: number; to_year: number; label: string; look: string; avoid: string[]; edited?: boolean };

const yearText = (y: number) => (y < 0 ? `${-y} BC` : `${y}`);

// What each phase of the story looked like. The AI's first guess can be wrong for an era it knows badly, so a curator
// can correct it; the video prompts, the negative prompts and the out-of-period checks all read this text.
export default function WorldPeriodEditor({ draftId, phases, editable, onChanged, onMessage }: {
  draftId: string; phases: Phase[]; editable: boolean; onChanged: () => void; onMessage: (message: string) => void;
}) {
  const [values, setValues] = useState(() => phases.map((p) => ({ label: p.label, look: p.look, avoid: (p.avoid || []).join(", ") })));
  const [busy, setBusy] = useState(false);
  const [conflicts, setConflicts] = useState<string[]>([]);
  const changed = phases.some((p, i) => values[i] && (values[i].label !== p.label || values[i].look !== p.look || values[i].avoid !== (p.avoid || []).join(", ")));

  async function save() {
    setBusy(true);
    try {
      const res = await fetch(`/api/admin/world-production/${draftId}/edit-period`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phases: values }),
      });
      const data = await res.json().catch(() => ({}));
      onMessage(res.ok ? data.message : (data.detail || "Could not save the period."));
      setConflicts(res.ok ? data.conflicts || [] : []);
      if (res.ok) onChanged();
    } finally { setBusy(false); }
  }

  if (!phases.length) return null;
  return <div className="rounded-md border border-gray-100 p-3">
    <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">What this place looked like</p>
    <p className="mt-1 text-xs text-gray-500">Each shot is drawn from the phase its year falls in. The AI wrote these from general knowledge and can be wrong for an early period. {editable ? "Correct anything that is not right: the video prompt and the checks follow your wording." : "It cannot be changed after the video is rendered."}</p>
    <div className="mt-3 space-y-4">{phases.map((p, i) => <div key={i}>
      <p className="text-xs font-semibold text-gray-700">{p.label} <span className="font-normal text-gray-400">({yearText(p.from_year)} to {yearText(p.to_year)}){p.edited ? " · edited by you" : ""}</span></p>
      {editable ? <>
        <label htmlFor={`look-${draftId}-${i}`} className="mt-1 block text-xs text-gray-500">What it looked like</label>
        <textarea id={`look-${draftId}-${i}`} rows={4} value={values[i]?.look ?? ""} onChange={(e) => setValues(values.map((v, j) => j === i ? { ...v, look: e.target.value } : v))}
          className="mt-1 w-full rounded-md border border-gray-200 px-2.5 py-2 text-sm focus:border-primary-500 focus:outline-none" />
        <label htmlFor={`avoid-${draftId}-${i}`} className="mt-2 block text-xs text-gray-500">Did not exist yet (comma separated)</label>
        <input id={`avoid-${draftId}-${i}`} value={values[i]?.avoid ?? ""} onChange={(e) => setValues(values.map((v, j) => j === i ? { ...v, avoid: e.target.value } : v))}
          className="mt-1 w-full rounded-md border border-gray-200 px-2.5 py-2 text-sm focus:border-primary-500 focus:outline-none" />
      </> : <>
        <p className="mt-1 text-xs text-gray-600 [overflow-wrap:anywhere]">{p.look}</p>
        {p.avoid?.length > 0 && <p className="mt-1 text-xs text-gray-400">Did not exist yet: {p.avoid.join(", ")}</p>}
      </>}
    </div>)}</div>
    {conflicts.length > 0 && <ul className="mt-3 list-disc space-y-1 rounded-md bg-amber-50 py-2 pl-6 pr-3 text-xs text-amber-800">{conflicts.map((c, i) => <li key={i} className="[overflow-wrap:anywhere]">{c}</li>)}</ul>}
    {editable && <div className="mt-3 flex flex-wrap items-center gap-2">
      <button disabled={busy || !changed} onClick={save} className="inline-flex min-h-10 items-center gap-1.5 rounded-md bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} {busy ? "Saving..." : "Save period"}</button>
      <span className="text-xs text-gray-400">Check the result under "What will be generated".</span>
    </div>}
  </div>;
}

"use client";

import { useEffect, useState } from "react";
import { Wand2, Plus, Loader2, Sparkles } from "lucide-react";
import type { ToonScript, CharacterVariant } from "@/lib/types";
import { TONE_OPTIONS } from "@/lib/types";

interface TrendSource {
  id: number;
  name: string;
  description: string | null;
}

interface Props {
  brandId: string;
  initialScripts: ToonScript[];
  variants: CharacterVariant[];
}

export default function ScriptManager({ brandId, initialScripts, variants }: Props) {
  const [scripts, setScripts] = useState(initialScripts);
  const [sourceType, setSourceType] = useState<"persona" | "cluster">("persona");
  const [trendSources, setTrendSources] = useState<{ personas: TrendSource[]; clusters: TrendSource[] }>({
    personas: [], clusters: [],
  });
  const [sourceId, setSourceId] = useState<string>("");
  const [variantId, setVariantId] = useState<string>(variants[0]?.id ?? "");
  const [tone, setTone] = useState<(typeof TONE_OPTIONS)[number]>("funny");
  const [suggesting, setSuggesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [manualHook, setManualHook] = useState("");
  const [manualDialogue, setManualDialogue] = useState("");
  const [manualScene, setManualScene] = useState("");
  const [manualVariantId, setManualVariantId] = useState<string>(variants[0]?.id ?? "");
  const [creatingManual, setCreatingManual] = useState(false);

  useEffect(() => {
    fetch("/api/culturetoons/trend-sources", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : { personas: [], clusters: [] }))
      .then(setTrendSources);
  }, []);

  const sourceOptions = sourceType === "persona" ? trendSources.personas : trendSources.clusters;

  async function suggest() {
    if (!sourceId) return;
    setSuggesting(true);
    setError(null);
    try {
      const res = await fetch("/api/culturetoons/scripts/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          source_type: sourceType,
          source_id: Number(sourceId),
          character_variant_id: variantId || undefined,
          tone,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Suggestion failed");
        return;
      }
      setScripts((prev) => [data, ...prev]);
    } finally {
      setSuggesting(false);
    }
  }

  function variantName(id: string | null) {
    return variants.find((v) => v.id === id)?.name ?? "—";
  }

  async function createManual(e: React.FormEvent) {
    e.preventDefault();
    if (!manualHook.trim() && !manualDialogue.trim()) return;
    setCreatingManual(true);
    try {
      const res = await fetch("/api/culturetoons/scripts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          character_variant_id: manualVariantId || undefined,
          hook_line: manualHook.trim() || undefined,
          dialogue: manualDialogue.trim() || undefined,
          scene_direction: manualScene.trim() || undefined,
        }),
      });
      if (res.ok) {
        const created = await res.json();
        setScripts((prev) => [created, ...prev]);
        setManualHook(""); setManualDialogue(""); setManualScene("");
      }
    } finally {
      setCreatingManual(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Write a script manually</h3>
        <form onSubmit={createManual} className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <input
            type="text" value={manualHook} onChange={(e) => setManualHook(e.target.value)}
            placeholder="Hook line, e.g. “Indian moms when you say you're not hungry.”"
            className="sm:col-span-2 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <input
            type="text" value={manualDialogue} onChange={(e) => setManualDialogue(e.target.value)}
            placeholder="Dialogue, e.g. Mom: “Okay… I'll make something small.”"
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <input
            type="text" value={manualScene} onChange={(e) => setManualScene(e.target.value)}
            placeholder="Scene direction, e.g. Cut to: 12 dishes."
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <select
            value={manualVariantId} onChange={(e) => setManualVariantId(e.target.value)}
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
          >
            <option value="">No specific character</option>
            {variants.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
          <button
            type="submit"
            disabled={creatingManual || (!manualHook.trim() && !manualDialogue.trim())}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
          >
            {creatingManual ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            Save script
          </button>
        </form>
      </div>

      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-blue-500" /> Suggest a script from a trend
        </h3>
        <div className="flex flex-wrap gap-2 items-center">
          <select
            value={sourceType}
            onChange={(e) => { setSourceType(e.target.value as "persona" | "cluster"); setSourceId(""); }}
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
          >
            <option value="persona">Persona</option>
            <option value="cluster">Cluster</option>
          </select>
          <select
            value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs min-w-[10rem]"
          >
            <option value="">Select a trending {sourceType}…</option>
            {sourceOptions.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <select
            value={variantId}
            onChange={(e) => setVariantId(e.target.value)}
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs min-w-[10rem]"
          >
            <option value="">No specific character</option>
            {variants.map((v) => (
              <option key={v.id} value={v.id}>{v.name}</option>
            ))}
          </select>
          <select
            value={tone}
            onChange={(e) => setTone(e.target.value as (typeof TONE_OPTIONS)[number])}
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs capitalize"
          >
            {TONE_OPTIONS.map((t) => (
              <option key={t} value={t} className="capitalize">{t}</option>
            ))}
          </select>
          <button
            onClick={suggest}
            disabled={suggesting || !sourceId}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
          >
            {suggesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
            Suggest script
          </button>
        </div>
        {error && <p className="text-xs text-red-500 mt-2">{error}</p>}
      </div>

      <div className="space-y-3">
        {scripts.length === 0 && (
          <p className="text-xs text-gray-400">No scripts yet — suggest one from a trend above, or write one manually.</p>
        )}
        {scripts.map((s) => (
          <div key={s.id} className="rounded-2xl bg-white border border-gray-100 p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-gray-400">
                {variantName(s.character_variant_id)}
                {s.generation_source === "ai" && (
                  <span className="ml-2 inline-flex items-center gap-1 text-blue-500 bg-blue-50 rounded-full px-2 py-0.5">
                    <Sparkles className="h-3 w-3" /> AI-suggested
                  </span>
                )}
                {s.tone && (
                  <span className="ml-2 inline-flex items-center capitalize text-gray-400 bg-gray-50 rounded-full px-2 py-0.5">
                    {s.tone}
                  </span>
                )}
              </span>
              <span className="text-[10px] uppercase tracking-wide text-gray-400">{s.status}</span>
            </div>
            {s.hook_line && <p className="text-sm font-medium text-gray-900">&quot;{s.hook_line}&quot;</p>}
            {s.dialogue && <p className="text-sm text-gray-600 mt-1">{s.dialogue}</p>}
            {s.scene_direction && <p className="text-xs text-gray-400 mt-1 italic">{s.scene_direction}</p>}
            {s.shots && s.shots.length > 0 && (
              <ol className="mt-2 space-y-1">
                {s.shots.map((shot) => (
                  <li key={shot.shot_number} className="text-xs text-gray-600">
                    <span className="text-gray-400">Shot {shot.shot_number} ({shot.duration_seconds}s):</span>{" "}
                    {shot.action}
                    {shot.expression && <span className="text-gray-400"> · {shot.expression}</span>}
                    {shot.dialogue && <span> — &quot;{shot.dialogue}&quot;</span>}
                  </li>
                ))}
              </ol>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

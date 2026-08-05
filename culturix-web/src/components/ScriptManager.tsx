"use client";

import { useEffect, useState } from "react";
import { Wand2, Plus, Loader2, Sparkles, ImageIcon } from "lucide-react";
import type { ToonScript, CharacterVariant, ToonBackground } from "@/lib/types";
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
  backgrounds: ToonBackground[];
}

function scriptHasScene(s: ToonScript): boolean {
  if (s.scene_direction && s.scene_direction.trim()) return true;
  return !!s.shots?.some((shot) => shot.action?.trim());
}

export default function ScriptManager({ brandId, initialScripts, variants, backgrounds }: Props) {
  const [scripts, setScripts] = useState(initialScripts);
  const [backgroundsState, setBackgroundsState] = useState(backgrounds);
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

  const [extraDescByScript, setExtraDescByScript] = useState<Record<string, string>>({});
  const [generatingBgFor, setGeneratingBgFor] = useState<string | null>(null);
  const [bgErrors, setBgErrors] = useState<Record<string, string>>({});

  const [idea, setIdea] = useState("");
  const [ideaVariantId, setIdeaVariantId] = useState<string>(variants[0]?.id ?? "");
  const [ideaTone, setIdeaTone] = useState<(typeof TONE_OPTIONS)[number]>("funny");
  const [suggestingFromIdea, setSuggestingFromIdea] = useState(false);
  const [ideaError, setIdeaError] = useState<string | null>(null);

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

  async function suggestFromIdea() {
    if (!idea.trim()) return;
    setSuggestingFromIdea(true);
    setIdeaError(null);
    try {
      const res = await fetch("/api/culturetoons/scripts/suggest-from-idea", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          idea: idea.trim(),
          character_variant_id: ideaVariantId || undefined,
          tone: ideaTone,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setIdeaError(typeof data.detail === "string" ? data.detail : "Suggestion failed");
        return;
      }
      setScripts((prev) => [data, ...prev]);
      setIdea("");
    } finally {
      setSuggestingFromIdea(false);
    }
  }

  function variantName(id: string | null) {
    return variants.find((v) => v.id === id)?.name ?? "—";
  }

  function backgroundFor(id: string | null) {
    return backgroundsState.find((b) => b.id === id) ?? null;
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

  async function generateBackground(scriptId: string) {
    setGeneratingBgFor(scriptId);
    setBgErrors((prev) => ({ ...prev, [scriptId]: "" }));
    try {
      const res = await fetch(`/api/culturetoons/scripts/${scriptId}/generate-background`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          extra_description: (extraDescByScript[scriptId] || "").trim() || undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setBgErrors((prev) => ({ ...prev, [scriptId]: typeof data.detail === "string" ? data.detail : "Background generation failed" }));
        return;
      }
      setBackgroundsState((prev) => [...prev, data as ToonBackground]);
      setScripts((prev) => prev.map((s) => (s.id === scriptId ? { ...s, background_id: data.id } : s)));
    } finally {
      setGeneratingBgFor(null);
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
          <Wand2 className="h-4 w-4 text-blue-500" /> Suggest a script from your own idea
        </h3>
        <p className="text-xs text-gray-400 mb-3">
          Already know what you want the character to react to? Describe the scenario and skip browsing trends.
        </p>
        <div className="flex flex-col gap-2">
          <textarea
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            placeholder={`E.g. "The character comes home to find their roommate ate their leftovers again."`}
            rows={2}
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <div className="flex flex-wrap gap-2 items-center">
            <select
              value={ideaVariantId}
              onChange={(e) => setIdeaVariantId(e.target.value)}
              className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs min-w-[10rem]"
            >
              <option value="">No specific character</option>
              {variants.map((v) => (
                <option key={v.id} value={v.id}>{v.name}</option>
              ))}
            </select>
            <select
              value={ideaTone}
              onChange={(e) => setIdeaTone(e.target.value as (typeof TONE_OPTIONS)[number])}
              className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs capitalize"
            >
              {TONE_OPTIONS.map((t) => (
                <option key={t} value={t} className="capitalize">{t}</option>
              ))}
            </select>
            <button
              onClick={suggestFromIdea}
              disabled={suggestingFromIdea || !idea.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
            >
              {suggestingFromIdea ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
              Suggest script
            </button>
          </div>
          {ideaError && <p className="text-xs text-red-500">{ideaError}</p>}
        </div>
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
        {scripts.map((s) => {
          const bg = backgroundFor(s.background_id);
          const hasScene = scriptHasScene(s);
          const generating = generatingBgFor === s.id;
          return (
            <div key={s.id} className="rounded-2xl bg-white border border-gray-100 p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-gray-400">
                  {variantName(s.character_variant_id)}
                  {s.generation_source === "ai" && (
                    <span className="ml-2 inline-flex items-center gap-1 text-blue-500 bg-blue-50 rounded-full px-2 py-0.5">
                      <Sparkles className="h-3 w-3" />
                      {s.source_type === "idea" ? "From your idea" : "AI-suggested"}
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

              <div className="mt-3 pt-3 border-t border-gray-50">
                {bg ? (
                  <div className="flex items-center gap-2.5">
                    {bg.image_url && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={bg.image_url} alt={bg.name} className="h-12 w-12 rounded-lg object-cover shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-gray-700 truncate">{bg.name}</p>
                      <button
                        onClick={() => generateBackground(s.id)}
                        disabled={generating}
                        className="text-[11px] text-blue-500 hover:underline disabled:opacity-50"
                      >
                        {generating ? "Regenerating…" : "Regenerate background"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="text"
                      value={extraDescByScript[s.id] ?? ""}
                      onChange={(e) => setExtraDescByScript((prev) => ({ ...prev, [s.id]: e.target.value }))}
                      placeholder={hasScene ? "Extra detail for the background (optional)" : "Describe the setting — no scene direction on this script yet"}
                      className="flex-1 min-w-[10rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
                    />
                    <button
                      onClick={() => generateBackground(s.id)}
                      disabled={generating || (!hasScene && !(extraDescByScript[s.id] ?? "").trim())}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60 shrink-0"
                    >
                      {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImageIcon className="h-3.5 w-3.5" />}
                      Generate background
                    </button>
                  </div>
                )}
                {bgErrors[s.id] && <p className="text-[11px] text-red-500 mt-1">{bgErrors[s.id]}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

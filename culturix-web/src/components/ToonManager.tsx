"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, ExternalLink, Clapperboard } from "lucide-react";
import type { Toon, ToonScript, CharacterVariant, ToonBackground } from "@/lib/types";

interface Props {
  brandId: string;
  initialToons: Toon[];
  scripts: ToonScript[];
  variants: CharacterVariant[];
  backgrounds: ToonBackground[];
}

const STATUSES: Toon["status"][] = ["idea", "animating", "ready", "posted", "archived"];

export default function ToonManager({ brandId, initialToons, scripts, variants, backgrounds }: Props) {
  const [toons, setToons] = useState(initialToons.filter((t) => t.status !== "archived"));
  const [variantId, setVariantId] = useState(variants[0]?.id ?? "");
  const [scriptId, setScriptId] = useState(scripts[0]?.id ?? "");
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [generatingId, setGeneratingId] = useState<string | null>(null);

  function variantName(id: string) {
    return variants.find((v) => v.id === id)?.name ?? "—";
  }

  function scriptFor(id: string) {
    return scripts.find((s) => s.id === id) ?? null;
  }

  function variantFor(id: string) {
    return variants.find((v) => v.id === id) ?? null;
  }

  // Poll toons that are mid-generation.
  useEffect(() => {
    const animating = toons.filter((t) => t.status === "animating");
    if (animating.length === 0) return;
    const interval = setInterval(async () => {
      for (const t of animating) {
        const res = await fetch(`/api/culturetoons/toons/${t.id}?brand_id=${brandId}`, { cache: "no-store" });
        if (res.ok) {
          const updated = await res.json();
          setToons((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
        }
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [toons, brandId]);

  async function createToon(e: React.FormEvent) {
    e.preventDefault();
    if (!variantId || !scriptId) return;
    setCreating(true);
    try {
      // A toon defaults to the background its script was generated for —
      // scripts drive backgrounds, not the reverse — but this stays
      // overridable per-toon via the background picker below once created.
      const inheritedBackgroundId = scriptFor(scriptId)?.background_id ?? undefined;
      const res = await fetch("/api/culturetoons/toons", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId, character_variant_id: variantId, script_id: scriptId,
          background_id: inheritedBackgroundId, title: title.trim() || undefined,
        }),
      });
      if (res.ok) {
        const created = await res.json();
        setToons((prev) => [created, ...prev]);
        setTitle("");
      }
    } finally {
      setCreating(false);
    }
  }

  async function updateToon(id: string, patch: Record<string, unknown>) {
    setToons((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } as Toon : t)));
    const res = await fetch(`/api/culturetoons/toons/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...patch, brand_id: brandId }),
    });
    if (res.ok) {
      const updated = await res.json();
      setToons((prev) => prev.map((t) => (t.id === id ? updated : t)));
    }
  }

  async function archiveToon(id: string) {
    setToons((prev) => prev.filter((t) => t.id !== id));
    await fetch(`/api/culturetoons/toons/${id}?brand_id=${brandId}`, { method: "DELETE" });
  }

  async function generateVideo(id: string) {
    setGeneratingId(id);
    try {
      const res = await fetch(`/api/culturetoons/toons/${id}/generate-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setToons((prev) => prev.map((t) => (t.id === id ? { ...t, ...data } as Toon : t)));
      } else {
        setToons((prev) => prev.map((t) => (t.id === id ? { ...t, generation_error: typeof data.detail === "string" ? data.detail : "Failed to start generation" } : t)));
      }
    } finally {
      setGeneratingId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Plan a new toon</h3>
        <form onSubmit={createToon} className="flex flex-wrap gap-2 items-center">
          <select value={variantId} onChange={(e) => setVariantId(e.target.value)} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs">
            {variants.length === 0 && <option value="">No characters yet</option>}
            {variants.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
          <select value={scriptId} onChange={(e) => setScriptId(e.target.value)} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs min-w-[10rem]">
            {scripts.length === 0 && <option value="">No scripts yet</option>}
            {scripts.map((s) => <option key={s.id} value={s.id}>{s.hook_line || s.dialogue || s.id.slice(0, 8)}</option>)}
          </select>
          <input
            type="text" value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder="Internal title (optional)"
            className="flex-1 min-w-[10rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
          />
          <button
            type="submit"
            disabled={creating || !variantId || !scriptId}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
          >
            {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            Add toon
          </button>
        </form>
      </div>

      <div className="space-y-3">
        {toons.length === 0 && <p className="text-xs text-gray-400">No toons planned yet.</p>}
        {toons.map((t) => {
          const script = scriptFor(t.script_id);
          const variant = variantFor(t.character_variant_id);
          const canGenerate = !!script?.shots?.length && variant?.element_status === "ready";
          const generating = generatingId === t.id || t.status === "animating";
          return (
            <div key={t.id} className="rounded-2xl bg-white border border-gray-100 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                <div>
                  <span className="text-sm font-medium text-gray-900">{t.title || variantName(t.character_variant_id)}</span>
                  <span className="text-xs text-gray-400 ml-2">{variantName(t.character_variant_id)}</span>
                </div>
                <select
                  value={t.status}
                  onChange={(e) => updateToon(t.id, { status: e.target.value })}
                  className="rounded-lg border border-gray-200 px-2 py-1 text-xs"
                >
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 items-center">
                <select
                  value={t.background_id ?? ""}
                  onChange={(e) => updateToon(t.id, { background_id: e.target.value || null })}
                  className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
                >
                  <option value="">No background chosen</option>
                  {backgrounds.map((bg) => <option key={bg.id} value={bg.id}>{bg.name}</option>)}
                </select>
                <input
                  type="text"
                  defaultValue={t.final_video_url ?? ""}
                  onBlur={(e) => { if (e.target.value !== (t.final_video_url ?? "")) updateToon(t.id, { final_video_url: e.target.value || null }); }}
                  placeholder="Final video URL"
                  className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
                />
                <input
                  type="text"
                  defaultValue={t.platform ?? ""}
                  onBlur={(e) => { if (e.target.value !== (t.platform ?? "")) updateToon(t.id, { platform: e.target.value || null }); }}
                  placeholder="Platform, e.g. tiktok"
                  className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
                />
              </div>

              <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 mt-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-semibold text-gray-700">AI video generation</span>
                  <button
                    onClick={() => generateVideo(t.id)}
                    disabled={!canGenerate || generating}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
                  >
                    {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Clapperboard className="h-3.5 w-3.5" />}
                    {t.raw_video_url ? "Regenerate" : "Generate video"}
                  </button>
                </div>
                {!canGenerate && !generating && (
                  <p className="text-[11px] text-gray-400">
                    {!script?.shots?.length
                      ? "This script has no AI-generated shots yet — suggest one from a trend to enable video generation."
                      : "This character isn't registered with Kling yet — register it in the Characters tab first."}
                  </p>
                )}
                {generating && <p className="text-[11px] text-amber-600">Generating — this can take a few minutes.</p>}
                {t.generation_error && <p className="text-[11px] text-red-500 mt-1">{t.generation_error}</p>}
                {t.clip_video_urls && t.clip_video_urls.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {t.clip_video_urls.map((url, i) => (
                      <a
                        key={url}
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-500 hover:underline"
                      >
                        <ExternalLink className="h-3 w-3" /> Clip {i + 1}
                      </a>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between mt-2">
                {t.final_video_url ? (
                  <a href={t.final_video_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-blue-500 hover:underline">
                    <ExternalLink className="h-3 w-3" /> View final video
                  </a>
                ) : <span />}
                <button onClick={() => archiveToon(t.id)} className="text-xs text-gray-400 hover:text-red-500">
                  Archive
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { Plus, Loader2, ExternalLink } from "lucide-react";
import type { Toon, ToonScript, CharacterVariant, ToonBackground } from "@/lib/types";

interface Props {
  initialToons: Toon[];
  scripts: ToonScript[];
  variants: CharacterVariant[];
  backgrounds: ToonBackground[];
}

const STATUSES: Toon["status"][] = ["idea", "animating", "ready", "posted", "archived"];

export default function ToonManager({ initialToons, scripts, variants, backgrounds }: Props) {
  const [toons, setToons] = useState(initialToons.filter((t) => t.status !== "archived"));
  const [variantId, setVariantId] = useState(variants[0]?.id ?? "");
  const [scriptId, setScriptId] = useState(scripts[0]?.id ?? "");
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  function variantName(id: string) {
    return variants.find((v) => v.id === id)?.name ?? "—";
  }

  async function createToon(e: React.FormEvent) {
    e.preventDefault();
    if (!variantId || !scriptId) return;
    setCreating(true);
    try {
      const res = await fetch("/api/culturetoons/toons", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character_variant_id: variantId, script_id: scriptId, title: title.trim() || undefined }),
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
      body: JSON.stringify(patch),
    });
    if (res.ok) {
      const updated = await res.json();
      setToons((prev) => prev.map((t) => (t.id === id ? updated : t)));
    }
  }

  async function archiveToon(id: string) {
    setToons((prev) => prev.filter((t) => t.id !== id));
    await fetch(`/api/culturetoons/toons/${id}`, { method: "DELETE" });
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
        {toons.map((t) => (
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
                placeholder="Final video URL (CapCut/Blender export)"
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
        ))}
      </div>
    </div>
  );
}

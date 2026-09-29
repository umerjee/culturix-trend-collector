"use client";

import { useEffect, useState } from "react";
import { Wand2, Loader2, ChevronDown } from "lucide-react";
import { TONE_OPTIONS } from "@/lib/types";
import type { ToonScript, CharacterVariant, CharacterBrand } from "@/lib/types";

const DURATION_PRESETS = [
  { key: "quick", label: "Quick (~15s)", numShots: 5, duration: 15 },
  { key: "standard", label: "Standard (~30s)", numShots: 9, duration: 30 },
  { key: "extended", label: "Extended (~60s)", numShots: 14, duration: 60 },
] as const;

// Admin-side counterpart to ScriptManager.tsx's "From an idea" flow. Confirmed live 2026-09-29:
// World Production has its own admin page to generate content directly; CultureToons script
// generation existed only inside the regular per-user dashboard (/dashboard/culturetoons), with
// nothing equivalent here -- a real feature-consistency gap, not an intentional split. This
// calls the EXACT SAME endpoint ScriptManager uses (/api/culturetoons/scripts/suggest-from-idea,
// which resolves user_id from whoever is logged in -- the admin's own account, since this page
// is already gated to a real superadmin session), so it generates into the admin's own real
// brand/cast, no separate admin-owned content model needed.
export default function GenerateScriptPanel() {
  const [open, setOpen] = useState(false);
  const [brands, setBrands] = useState<CharacterBrand[]>([]);
  const [brandId, setBrandId] = useState("");
  const [variants, setVariants] = useState<CharacterVariant[]>([]);
  const [variantIds, setVariantIds] = useState<string[]>([]);
  const [idea, setIdea] = useState("");
  const [tone, setTone] = useState<(typeof TONE_OPTIONS)[number]>("funny");
  const [durationKey, setDurationKey] = useState<(typeof DURATION_PRESETS)[number]["key"]>("quick");
  const [loadingVariants, setLoadingVariants] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ToonScript | null>(null);

  useEffect(() => {
    if (!open || brands.length > 0) return;
    fetch("/api/culturetoons/brands")
      .then((r) => r.json())
      .then((data) => {
        const list = Array.isArray(data) ? data : [];
        setBrands(list);
        if (list.length === 1) setBrandId(list[0].id);
      })
      .catch(() => setBrands([]));
  }, [open, brands.length]);

  useEffect(() => {
    if (!brandId) { setVariants([]); setVariantIds([]); return; }
    setLoadingVariants(true);
    fetch(`/api/culturetoons/variants?brand_id=${brandId}`)
      .then((r) => r.json())
      .then((data) => setVariants(Array.isArray(data) ? data : []))
      .catch(() => setVariants([]))
      .finally(() => setLoadingVariants(false));
  }, [brandId]);

  function toggleVariant(id: string) {
    setVariantIds((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]));
  }

  async function generate() {
    if (!brandId || !idea.trim() || variantIds.length === 0) return;
    const preset = DURATION_PRESETS.find((p) => p.key === durationKey) ?? DURATION_PRESETS[0];
    setGenerating(true);
    setError("");
    setResult(null);
    try {
      const res = await fetch("/api/culturetoons/scripts/suggest-from-idea", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId, idea: idea.trim(), character_variant_ids: variantIds,
          tone, num_shots: preset.numShots, target_duration_seconds: preset.duration,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setError(typeof data.detail === "string" ? data.detail : "Script generation failed."); return; }
      setResult(data);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <section className="rounded-xl border border-gray-100 bg-white">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex min-h-11 w-full items-center justify-between gap-3 px-4 py-3 text-left">
        <span className="flex items-center gap-2 text-sm font-semibold text-gray-900"><Wand2 className="h-4 w-4 text-primary-600" /> Generate a script</span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="space-y-3 border-t border-gray-100 px-4 py-4">
        <p className="text-xs text-gray-500">
          Generates into your own CultureToons account — the same endpoint the regular dashboard
          uses, so the &quot;funny&quot; tone below already pulls in the real comedy-pattern data
          shown on this page.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-xs font-medium text-gray-600">Brand</span>
            <select value={brandId} onChange={(e) => setBrandId(e.target.value)} className="mt-1 w-full rounded-md border border-gray-200 px-2.5 py-2 text-sm">
              <option value="">{brands.length === 0 ? "Loading..." : "Select a brand"}</option>
              {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-gray-600">Tone</span>
            <select value={tone} onChange={(e) => setTone(e.target.value as (typeof TONE_OPTIONS)[number])} className="mt-1 w-full rounded-md border border-gray-200 px-2.5 py-2 text-sm">
              {TONE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
        </div>

        {brandId && <div>
          <span className="text-xs font-medium text-gray-600">Cast</span>
          {loadingVariants ? <p className="mt-1 text-xs text-gray-400">Loading cast...</p> :
            variants.length === 0 ? <p className="mt-1 text-xs text-gray-400">This brand has no characters yet — add one in the regular dashboard first.</p> :
            <div className="mt-1 flex flex-wrap gap-2">
              {variants.map((v) => (
                <button key={v.id} type="button" onClick={() => toggleVariant(v.id)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-medium ${variantIds.includes(v.id) ? "border-primary-600 bg-primary-50 text-primary-700" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
                  {v.name}
                </button>
              ))}
            </div>}
        </div>}

        <label className="block">
          <span className="text-xs font-medium text-gray-600">Idea / premise</span>
          <textarea value={idea} onChange={(e) => setIdea(e.target.value)} rows={2} maxLength={500}
            placeholder="e.g. Three roommates from different countries argue about how to make tea"
            className="mt-1 w-full rounded-md border border-gray-200 px-2.5 py-2 text-sm placeholder:text-gray-300" />
        </label>

        <label className="block max-w-xs">
          <span className="text-xs font-medium text-gray-600">Length</span>
          <select value={durationKey} onChange={(e) => setDurationKey(e.target.value as (typeof DURATION_PRESETS)[number]["key"])} className="mt-1 w-full rounded-md border border-gray-200 px-2.5 py-2 text-sm">
            {DURATION_PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </label>

        <button disabled={generating || !brandId || !idea.trim() || variantIds.length === 0} onClick={generate}
          className="inline-flex min-h-10 items-center gap-1.5 rounded-md bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
          {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />} {generating ? "Generating..." : "Generate script"}
        </button>

        {error && <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}

        {result && <div className="rounded-lg border border-gray-100 bg-gray-50 p-3 text-sm">
          {result.comedy_judgment?.comedy_score != null && <p className="mb-2 text-xs font-semibold text-primary-700">
            Comedy score {result.comedy_judgment.comedy_score}/100{result.comedy_judgment.passes_bar ? " · passes the bar" : ""}
          </p>}
          {result.comedy_judgment?.feedback && <p className="mb-2 text-xs text-gray-500">{result.comedy_judgment.feedback}</p>}
          <p className="font-semibold text-gray-900">{result.hook_line}</p>
          <ol className="mt-2 space-y-2">
            {(result.shots || []).map((s) => (
              <li key={s.shot_number} className="text-xs text-gray-700">
                <span className="font-semibold">Shot {s.shot_number}</span>{s.dialogue && <>: &quot;{s.dialogue}&quot;</>}
                {s.visual && <span className="block text-gray-500">{s.visual}</span>}
              </li>
            ))}
          </ol>
        </div>}
      </div>}
    </section>
  );
}

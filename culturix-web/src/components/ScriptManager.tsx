"use client";

import { useEffect, useState } from "react";
import { Wand2, Plus, Loader2, Sparkles, ImageIcon, Check, Target, Pencil, Trash2, Film } from "lucide-react";
import type { ToonScript, ToonScriptShot, CharacterVariant, ToonBackground } from "@/lib/types";
import { TONE_OPTIONS, MAX_CHARACTERS_PER_VIDEO, ART_STYLES, EXPRESSION_NAMES } from "@/lib/types";

// Backgrounds pick their own rendering style independently of the
// character's art_style — a background is composited separately at
// video-generation time (Kling adds the character element on top), so
// there's no requirement the two match. Defaults to the painterly
// "Cinematic cultural" look rather than DEFAULT_ART_STYLE's Pixar-cartoon
// look, since this product's scenes are grounded in real-world cultural
// settings that read better in that style.
const DEFAULT_BACKGROUND_STYLE = "cinematic_cultural";

interface TrendSource {
  id: number;
  name: string;
  description: string | null;
}

// Bundles num_shots + target_duration_seconds into one intuitive control.
// A script itself is provider-agnostic (server-side ceiling is now
// MIN_SHOTS/MAX_SHOTS/MIN_TOTAL_SECONDS/MAX_TOTAL_SECONDS in
// app/services/culturetoon_script.py, 2-15 shots / 3-60s) — these presets
// match real short-form social lengths (TikTok/Reels/Shorts' own common
// tiers) rather than Kling Omni's much smaller real per-call ceiling
// (KLING_MAX_SHOTS/KLING_MAX_TOTAL_SECONDS, 6 shots/15s, enforced
// separately at generate-time). Only "Quick" fits within that Kling
// ceiling — Standard/Extended need self-hosted generation.
const DURATION_PRESETS = [
  { key: "quick", label: "Quick (~15s)", numShots: 5, duration: 15 },
  { key: "standard", label: "Standard (~30s) — self-hosted only", numShots: 9, duration: 30 },
  { key: "extended", label: "Extended (~60s) — self-hosted only", numShots: 14, duration: 60 },
] as const;

interface Props {
  brandId: string;
  // scripts/backgrounds are lifted up to CultureToonWorkspace and shared
  // read/write with Toons/Episodes (backgrounds also with the Locations
  // tab) so a script's own "generate a background" doesn't go stale
  // elsewhere, and vice versa — see that file for why.
  scripts: ToonScript[];
  setScripts: React.Dispatch<React.SetStateAction<ToonScript[]>>;
  variants: CharacterVariant[];
  backgrounds: ToonBackground[];
  setBackgrounds: React.Dispatch<React.SetStateAction<ToonBackground[]>>;
  initialTrendInterests: string | null;
}

// Toggleable chip for picking a scene's cast — same visual pattern as
// CultureToonBrandForm.tsx's PlatformChip, capped at
// MAX_CHARACTERS_PER_VIDEO so a scene can't be built that Kling can never
// actually generate (see MAX_CHARACTERS_PER_VIDEO in
// app/services/culturetoon_video.py).
function CastChip({ label, selected, disabled, onClick }: { label: string; selected: boolean; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        selected ? "bg-blue-600 border-blue-600 text-white" : "bg-white border-gray-200 text-gray-600 hover:border-blue-300"
      }`}
    >
      {selected && <Check className="h-3 w-3" />}
      {label}
    </button>
  );
}

function scriptHasScene(s: ToonScript): boolean {
  if (s.scene_direction && s.scene_direction.trim()) return true;
  return !!s.shots?.some((shot) => shot.action?.trim());
}

export default function ScriptManager({ brandId, scripts, setScripts, variants, backgrounds, setBackgrounds, initialTrendInterests }: Props) {
  const [sourceType, setSourceType] = useState<"persona" | "cluster">("persona");
  const [trendSources, setTrendSources] = useState<{ personas: TrendSource[]; clusters: TrendSource[] }>({
    personas: [], clusters: [],
  });
  const [sourceId, setSourceId] = useState<string>("");
  const [variantIds, setVariantIds] = useState<string[]>(variants[0] ? [variants[0].id] : []);
  const [tone, setTone] = useState<(typeof TONE_OPTIONS)[number]>("funny");
  const [lengthKey, setLengthKey] = useState<(typeof DURATION_PRESETS)[number]["key"]>("standard");
  const [suggesting, setSuggesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [manualHook, setManualHook] = useState("");
  const [manualDialogue, setManualDialogue] = useState("");
  const [manualScene, setManualScene] = useState("");
  const [manualVariantId, setManualVariantId] = useState<string>(variants[0]?.id ?? "");
  const [creatingManual, setCreatingManual] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);
  const [statusErrors, setStatusErrors] = useState<Record<string, string>>({});

  // Edit-in-place for an existing script's flat fields + shots.
  const [editingScriptId, setEditingScriptId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<{
    hook_line: string; dialogue: string; scene_direction: string; shots: ToonScriptShot[] | null;
  } | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Re-run AI generation for an existing script, in place.
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const [regenerateErrors, setRegenerateErrors] = useState<Record<string, string>>({});

  const [extraDescByScript, setExtraDescByScript] = useState<Record<string, string>>({});
  const [bgStyleByScript, setBgStyleByScript] = useState<Record<string, string>>({});
  const [generatingBgFor, setGeneratingBgFor] = useState<string | null>(null);
  const [bgErrors, setBgErrors] = useState<Record<string, string>>({});

  // "Compose episode" — the macro-script feature. Selection order matters
  // (becomes part order), so this is an ordered array, not a Set.
  const [composeIds, setComposeIds] = useState<string[]>([]);
  const [composeTitle, setComposeTitle] = useState("");
  const [composing, setComposing] = useState(false);
  const [composeError, setComposeError] = useState<string | null>(null);
  const [composeResult, setComposeResult] = useState<string | null>(null);
  const [composeProgress, setComposeProgress] = useState<Record<string, "queued" | "generating" | "ready" | "failed">>({});
  const MAX_COMPOSE_SCRIPTS = 10;

  function toggleCompose(scriptId: string) {
    setComposeIds((prev) => {
      if (prev.includes(scriptId)) return prev.filter((id) => id !== scriptId);
      if (prev.length >= MAX_COMPOSE_SCRIPTS) return prev;
      return [...prev, scriptId];
    });
  }

  async function pollToonUntilDone(toonId: string): Promise<{ status: string; error?: string | null }> {
    // Same 4s interval as the existing per-toon polls elsewhere
    // (ToonManager.tsx, EpisodeManager.tsx) — capped at 15 minutes, the
    // longest either provider's generation is expected to reasonably take.
    for (let i = 0; i < 225; i++) {
      const res = await fetch(`/api/culturetoons/toons/${toonId}?brand_id=${brandId}`, { cache: "no-store" });
      if (res.ok) {
        const toon = await res.json();
        if (toon.status !== "animating") return { status: toon.status, error: toon.generation_error };
      }
      await new Promise((resolve) => setTimeout(resolve, 4000));
    }
    return { status: "failed", error: "Timed out waiting for generation" };
  }

  async function composeEpisode() {
    if (composeIds.length < 2) return;
    setComposing(true);
    setComposeError(null);
    setComposeResult(null);
    setComposeProgress(Object.fromEntries(composeIds.map((id) => [id, "queued"])));
    try {
      const episodeRes = await fetch("/api/culturetoons/episodes", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, title: composeTitle.trim() || undefined }),
      });
      if (!episodeRes.ok) {
        const data = await episodeRes.json().catch(() => ({}));
        setComposeError(typeof data.detail === "string" ? data.detail : `Couldn't create the episode (${episodeRes.status})`);
        return;
      }
      const episode = await episodeRes.json();

      let readyCount = 0;
      for (const scriptId of composeIds) {
        const script = scripts.find((s) => s.id === scriptId);
        if (!script) continue;
        setComposeProgress((prev) => ({ ...prev, [scriptId]: "generating" }));

        const castVariantId = script.character_variant_ids?.[0] || script.character_variant_id || variants[0]?.id;
        const toonRes = await fetch("/api/culturetoons/toons", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            brand_id: brandId, script_id: scriptId, character_variant_id: castVariantId,
            background_id: script.background_id ?? undefined, title: script.hook_line || undefined,
          }),
        });
        if (!toonRes.ok) {
          setComposeProgress((prev) => ({ ...prev, [scriptId]: "failed" }));
          continue;
        }
        const toon = await toonRes.json();

        const genRes = await fetch(`/api/culturetoons/toons/${toon.id}/generate-video`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brand_id: brandId }),
        });
        if (!genRes.ok) {
          setComposeProgress((prev) => ({ ...prev, [scriptId]: "failed" }));
          continue;
        }

        const { status } = await pollToonUntilDone(toon.id);
        if (status !== "ready") {
          setComposeProgress((prev) => ({ ...prev, [scriptId]: "failed" }));
          continue;
        }

        const attachRes = await fetch(`/api/culturetoons/episodes/${episode.id}/parts`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brand_id: brandId, toon_id: toon.id }),
        });
        if (!attachRes.ok) {
          setComposeProgress((prev) => ({ ...prev, [scriptId]: "failed" }));
          continue;
        }
        setComposeProgress((prev) => ({ ...prev, [scriptId]: "ready" }));
        readyCount++;
      }

      if (readyCount >= 2) {
        await fetch(`/api/culturetoons/episodes/${episode.id}/stitch`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brand_id: brandId }),
        });
        setComposeResult(`Episode composed from ${readyCount}/${composeIds.length} scripts — stitching now, check the Episodes tab.`);
      } else {
        setComposeResult(`Only ${readyCount}/${composeIds.length} scripts made it to a finished video — not enough to stitch (need at least 2). The episode is still there in the Episodes tab if you want to add more parts manually.`);
      }
      setComposeIds([]);
      setComposeTitle("");
    } catch {
      setComposeError("Network error partway through — some scripts above may have already generated a toon; check the Toons/Episodes tabs before retrying.");
    } finally {
      setComposing(false);
    }
  }

  const [idea, setIdea] = useState("");
  const [ideaVariantIds, setIdeaVariantIds] = useState<string[]>(variants[0] ? [variants[0].id] : []);
  const [ideaTone, setIdeaTone] = useState<(typeof TONE_OPTIONS)[number]>("funny");
  const [ideaLengthKey, setIdeaLengthKey] = useState<(typeof DURATION_PRESETS)[number]["key"]>("standard");
  const [suggestingFromIdea, setSuggestingFromIdea] = useState(false);
  const [ideaError, setIdeaError] = useState<string | null>(null);
  const [trendsPersonalized, setTrendsPersonalized] = useState(false);
  const [trendInterests, setTrendInterests] = useState(initialTrendInterests ?? "");
  const [savingInterests, setSavingInterests] = useState(false);
  const [interestsError, setInterestsError] = useState<string | null>(null);
  const [interestsEditing, setInterestsEditing] = useState(false);

  function loadTrendSources() {
    fetch(`/api/culturetoons/trend-sources?brand_id=${brandId}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : { personas: [], clusters: [], personalized: false }))
      .then((data) => {
        setTrendSources({ personas: data.personas ?? [], clusters: data.clusters ?? [] });
        setTrendsPersonalized(!!data.personalized);
      });
  }

  useEffect(loadTrendSources, [brandId]);

  async function saveTrendInterests() {
    setSavingInterests(true);
    setInterestsError(null);
    try {
      const res = await fetch(`/api/culturetoons/brands/${brandId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trend_interests: trendInterests.trim() || null }),
      });
      if (res.ok) {
        setInterestsEditing(false);
        loadTrendSources();
      } else {
        const data = await res.json().catch(() => ({}));
        setInterestsError(typeof data.detail === "string" ? data.detail : `Couldn't save interests (${res.status})`);
      }
    } catch {
      setInterestsError("Network error — check your connection and try again.");
    } finally {
      setSavingInterests(false);
    }
  }

  const sourceOptions = sourceType === "persona" ? trendSources.personas : trendSources.clusters;

  function toggleCast(setIds: React.Dispatch<React.SetStateAction<string[]>>, id: string) {
    setIds((prev) => {
      if (prev.includes(id)) return prev.filter((v) => v !== id);
      if (prev.length >= MAX_CHARACTERS_PER_VIDEO) return prev;
      return [...prev, id];
    });
  }

  async function suggest() {
    if (!sourceId || variantIds.length === 0) return;
    const preset = DURATION_PRESETS.find((p) => p.key === lengthKey) ?? DURATION_PRESETS[1];
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
          character_variant_ids: variantIds,
          tone,
          num_shots: preset.numShots,
          target_duration_seconds: preset.duration,
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
    if (!idea.trim() || ideaVariantIds.length === 0) return;
    const preset = DURATION_PRESETS.find((p) => p.key === ideaLengthKey) ?? DURATION_PRESETS[1];
    setSuggestingFromIdea(true);
    setIdeaError(null);
    try {
      const res = await fetch("/api/culturetoons/scripts/suggest-from-idea", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          idea: idea.trim(),
          character_variant_ids: ideaVariantIds,
          tone: ideaTone,
          num_shots: preset.numShots,
          target_duration_seconds: preset.duration,
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

  function castNames(s: ToonScript) {
    const ids = s.character_variant_ids?.length ? s.character_variant_ids : s.character_variant_id ? [s.character_variant_id] : [];
    if (ids.length === 0) return "—";
    return ids.map((id) => variantName(id)).join(" & ");
  }

  function backgroundFor(id: string | null) {
    return backgrounds.find((b) => b.id === id) ?? null;
  }

  async function createManual(e: React.FormEvent) {
    e.preventDefault();
    if (!manualHook.trim() && !manualDialogue.trim()) return;
    setCreatingManual(true);
    setManualError(null);
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
      } else {
        const data = await res.json().catch(() => ({}));
        setManualError(typeof data.detail === "string" ? data.detail : `Couldn't save script (${res.status})`);
      }
    } catch {
      setManualError("Network error — check your connection and try again.");
    } finally {
      setCreatingManual(false);
    }
  }

  async function updateScriptStatus(scriptId: string, status: "approved" | "archived") {
    setStatusErrors((prev) => ({ ...prev, [scriptId]: "" }));
    try {
      const res = await fetch(`/api/culturetoons/scripts/${scriptId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, status }),
      });
      if (res.ok) {
        // Archiving removes the card outright rather than leaving a
        // permanent "archived"-labeled ghost behind — approving still
        // updates in place since that script stays relevant.
        if (status === "archived") {
          setScripts((prev) => prev.filter((s) => s.id !== scriptId));
        } else {
          const updated = await res.json();
          setScripts((prev) => prev.map((s) => (s.id === scriptId ? updated : s)));
        }
      } else {
        const data = await res.json().catch(() => ({}));
        setStatusErrors((prev) => ({ ...prev, [scriptId]: typeof data.detail === "string" ? data.detail : `Couldn't update (${res.status})` }));
      }
    } catch {
      setStatusErrors((prev) => ({ ...prev, [scriptId]: "Network error — check your connection and try again." }));
    }
  }

  function startEdit(s: ToonScript) {
    setEditingScriptId(s.id);
    setEditDraft({
      hook_line: s.hook_line ?? "", dialogue: s.dialogue ?? "", scene_direction: s.scene_direction ?? "",
      shots: s.shots ? s.shots.map((sh) => ({ ...sh })) : null,
    });
    setEditError(null);
  }

  function cancelEdit() {
    setEditingScriptId(null);
    setEditDraft(null);
    setEditError(null);
  }

  function updateEditShotField(index: number, field: keyof ToonScriptShot, value: string | number | null) {
    setEditDraft((prev) => {
      if (!prev?.shots) return prev;
      const shots = prev.shots.map((sh, i) => (i === index ? { ...sh, [field]: value } : sh));
      return { ...prev, shots };
    });
  }

  async function saveEdit(scriptId: string) {
    if (!editDraft) return;
    setSavingEdit(true);
    setEditError(null);
    try {
      const res = await fetch(`/api/culturetoons/scripts/${scriptId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          hook_line: editDraft.hook_line.trim() || null,
          dialogue: editDraft.dialogue.trim() || null,
          scene_direction: editDraft.scene_direction.trim() || null,
          ...(editDraft.shots ? { shots: editDraft.shots } : {}),
        }),
      });
      if (res.ok) {
        const updated = await res.json();
        setScripts((prev) => prev.map((s) => (s.id === scriptId ? updated : s)));
        setEditingScriptId(null);
        setEditDraft(null);
      } else {
        const data = await res.json().catch(() => ({}));
        setEditError(typeof data.detail === "string" ? data.detail : `Couldn't save (${res.status})`);
      }
    } catch {
      setEditError("Network error — check your connection and try again.");
    } finally {
      setSavingEdit(false);
    }
  }

  async function regenerateScript(scriptId: string) {
    setRegeneratingId(scriptId);
    setRegenerateErrors((prev) => ({ ...prev, [scriptId]: "" }));
    try {
      const res = await fetch(`/api/culturetoons/scripts/${scriptId}/regenerate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      if (res.ok) {
        const updated = await res.json();
        setScripts((prev) => prev.map((s) => (s.id === scriptId ? updated : s)));
      } else {
        const data = await res.json().catch(() => ({}));
        setRegenerateErrors((prev) => ({ ...prev, [scriptId]: typeof data.detail === "string" ? data.detail : `Couldn't regenerate (${res.status})` }));
      }
    } catch {
      setRegenerateErrors((prev) => ({ ...prev, [scriptId]: "Network error — check your connection and try again." }));
    } finally {
      setRegeneratingId(null);
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
          art_style: bgStyleByScript[scriptId] ?? DEFAULT_BACKGROUND_STYLE,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setBgErrors((prev) => ({ ...prev, [scriptId]: typeof data.detail === "string" ? data.detail : "Background generation failed" }));
        return;
      }
      setBackgrounds((prev) => [...prev, data as ToonBackground]);
      setScripts((prev) => prev.map((s) => (s.id === scriptId ? { ...s, background_id: data.id } : s)));
    } finally {
      setGeneratingBgFor(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Step 1 · Create a script</h3>
        <p className="text-xs text-gray-400 mt-0.5">
          Pick any one of the three ways below. Note: only the two AI-suggested options produce the
          shot-by-shot breakdown video generation actually needs — a manually-written script is great
          for keeping notes/ideas, but can&apos;t drive video generation on its own.
        </p>
      </div>

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
        {manualError && <p className="text-xs text-red-500 mt-2">{manualError}</p>}
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
          {variants.length === 0 ? (
            <p className="text-xs text-gray-400">Add a character first (Characters tab).</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {variants.map((v) => (
                <CastChip
                  key={v.id}
                  label={v.name}
                  selected={ideaVariantIds.includes(v.id)}
                  disabled={!ideaVariantIds.includes(v.id) && ideaVariantIds.length >= MAX_CHARACTERS_PER_VIDEO}
                  onClick={() => toggleCast(setIdeaVariantIds, v.id)}
                />
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-2 items-center">
            <select
              value={ideaTone}
              onChange={(e) => setIdeaTone(e.target.value as (typeof TONE_OPTIONS)[number])}
              className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs capitalize"
            >
              {TONE_OPTIONS.map((t) => (
                <option key={t} value={t} className="capitalize">{t}</option>
              ))}
            </select>
            <select
              value={ideaLengthKey}
              onChange={(e) => setIdeaLengthKey(e.target.value as (typeof DURATION_PRESETS)[number]["key"])}
              className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
            >
              {DURATION_PRESETS.map((p) => (
                <option key={p.key} value={p.key}>{p.label}</option>
              ))}
            </select>
            <button
              onClick={suggestFromIdea}
              disabled={suggestingFromIdea || !idea.trim() || ideaVariantIds.length === 0}
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
        <h3 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-blue-500" /> Suggest a script from a trend
        </h3>

        <div className="rounded-xl bg-gray-50 border border-gray-100 px-3 py-2 mb-3">
          {interestsEditing ? (
            <div className="flex flex-wrap gap-2 items-center">
              <input
                type="text"
                value={trendInterests}
                onChange={(e) => setTrendInterests(e.target.value)}
                placeholder='e.g. "family comedy, workplace awkwardness, cultural misunderstandings"'
                className="flex-1 min-w-[14rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
              />
              <button
                onClick={saveTrendInterests}
                disabled={savingInterests}
                className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
              >
                {savingInterests ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                Save
              </button>
              <button onClick={() => { setInterestsEditing(false); setTrendInterests(initialTrendInterests ?? ""); }} className="text-xs text-gray-400 hover:text-gray-600">
                Cancel
              </button>
              {interestsError && <p className="w-full text-[11px] text-red-500">{interestsError}</p>}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Target className="h-3.5 w-3.5 text-gray-400 shrink-0" />
              <p className="flex-1 text-[11px] text-gray-500">
                {trendsPersonalized ? (
                  <>Showing trends matched to: <span className="text-gray-700">{trendInterests}</span></>
                ) : trendInterests ? (
                  "Matching trends to your interests…"
                ) : (
                  "Showing the general trend feed — set what this brand's scripts should be about to personalize it."
                )}
              </p>
              <button onClick={() => setInterestsEditing(true)} className="inline-flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-700 shrink-0">
                <Pencil className="h-3 w-3" /> {trendInterests ? "Edit" : "Set interests"}
              </button>
            </div>
          )}
        </div>

        {variants.length === 0 ? (
          <p className="text-xs text-gray-400 mb-3">Add a character first (Characters tab).</p>
        ) : (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {variants.map((v) => (
              <CastChip
                key={v.id}
                label={v.name}
                selected={variantIds.includes(v.id)}
                disabled={!variantIds.includes(v.id) && variantIds.length >= MAX_CHARACTERS_PER_VIDEO}
                onClick={() => toggleCast(setVariantIds, v.id)}
              />
            ))}
          </div>
        )}
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
            value={tone}
            onChange={(e) => setTone(e.target.value as (typeof TONE_OPTIONS)[number])}
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs capitalize"
          >
            {TONE_OPTIONS.map((t) => (
              <option key={t} value={t} className="capitalize">{t}</option>
            ))}
          </select>
          <select
            value={lengthKey}
            onChange={(e) => setLengthKey(e.target.value as (typeof DURATION_PRESETS)[number]["key"])}
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
          >
            {DURATION_PRESETS.map((p) => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
          </select>
          <button
            onClick={suggest}
            disabled={suggesting || !sourceId || variantIds.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
          >
            {suggesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
            Suggest script
          </button>
        </div>
        {error && <p className="text-xs text-red-500 mt-2">{error}</p>}
      </div>

      {scripts.filter((s) => s.shots && s.shots.length > 0).length >= 2 && (
        <div className="rounded-2xl bg-white border border-gray-100 p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-1 flex items-center gap-1.5">
            <Film className="h-4 w-4 text-blue-500" /> Compose an episode from your scripts
          </h3>
          <p className="text-xs text-gray-400 mb-3">
            Pick 2-{MAX_COMPOSE_SCRIPTS} scripts below (in the order you want them to play) — each becomes its
            own generated toon, then they&apos;re stitched into one longer episode automatically. Only
            shot-structured scripts (AI-suggested, not manual) can be picked. Keep this tab open while it runs —
            each generation can take a few minutes.
          </p>
          <div className="flex flex-wrap gap-1.5 mb-3">
            {scripts.filter((s) => s.shots && s.shots.length > 0).map((s) => {
              const order = composeIds.indexOf(s.id);
              const label = s.hook_line || s.dialogue || s.id.slice(0, 8);
              return (
                <CastChip
                  key={s.id}
                  label={order >= 0 ? `${order + 1}. ${label}` : label}
                  selected={order >= 0}
                  disabled={composing || (order < 0 && composeIds.length >= MAX_COMPOSE_SCRIPTS)}
                  onClick={() => toggleCompose(s.id)}
                />
              );
            })}
          </div>
          <div className="flex flex-wrap gap-2 items-center">
            <input
              type="text" value={composeTitle} onChange={(e) => setComposeTitle(e.target.value)}
              placeholder="Episode title (optional)"
              className="flex-1 min-w-[10rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
            />
            <button
              onClick={composeEpisode}
              disabled={composing || composeIds.length < 2}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
            >
              {composing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Film className="h-3.5 w-3.5" />}
              Compose episode
            </button>
          </div>
          {composeIds.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {composeIds.map((id, i) => {
                const s = scripts.find((sc) => sc.id === id);
                const status = composeProgress[id];
                return (
                  <span key={id} className="inline-flex items-center gap-1 text-[10px] text-gray-500 rounded-full bg-gray-50 px-2 py-1">
                    {status === "generating" && <Loader2 className="h-3 w-3 animate-spin text-amber-500" />}
                    {status === "ready" && <Check className="h-3 w-3 text-emerald-500" />}
                    {i + 1}. {(s?.hook_line || s?.dialogue || id.slice(0, 8)).slice(0, 24)}
                    {status === "failed" && <span className="text-red-500">failed</span>}
                  </span>
                );
              })}
            </div>
          )}
          {composeError && <p className="text-xs text-red-500 mt-2">{composeError}</p>}
          {composeResult && <p className="text-xs text-primary-500 mt-2">{composeResult}</p>}
        </div>
      )}

      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-900">Step 2 · Your scripts</h3>
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
                  {castNames(s)}
                  {s.generation_source === "ai" && (
                    <span className="ml-2 inline-flex items-center gap-1 text-blue-500 bg-blue-50 rounded-full px-2 py-0.5">
                      <Sparkles className="h-3 w-3" />
                      {s.source_type === "idea" ? "From your idea" : "AI-suggested"}
                    </span>
                  )}
                  {s.generation_source === "ai_auto" && (
                    <span className="ml-2 inline-flex items-center gap-1 text-amber-600 bg-amber-50 rounded-full px-2 py-0.5">
                      <Sparkles className="h-3 w-3" />
                      Trending now — no one asked for this one
                    </span>
                  )}
                  {s.tone && (
                    <span className="ml-2 inline-flex items-center capitalize text-gray-400 bg-gray-50 rounded-full px-2 py-0.5">
                      {s.tone}
                    </span>
                  )}
                </span>
                <span className="flex items-center gap-2 shrink-0">
                  <span className="text-[10px] uppercase tracking-wide text-gray-400">{s.status}</span>
                  {s.generation_source !== "manual" && (
                    <button
                      onClick={() => regenerateScript(s.id)}
                      disabled={regeneratingId === s.id || editingScriptId === s.id}
                      title="Regenerate this script with AI, replacing its content"
                      className="text-gray-300 hover:text-blue-500 transition-colors disabled:opacity-40"
                    >
                      {regeneratingId === s.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                    </button>
                  )}
                  <button
                    onClick={() => (editingScriptId === s.id ? cancelEdit() : startEdit(s))}
                    title={editingScriptId === s.id ? "Cancel editing" : "Edit this script"}
                    className="text-gray-300 hover:text-gray-600 transition-colors"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => updateScriptStatus(s.id, "archived")}
                    title="Delete this script"
                    className="text-gray-300 hover:text-red-500 transition-colors"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </span>
              </div>
              {regenerateErrors[s.id] && <p className="text-[11px] text-red-500 mb-2">{regenerateErrors[s.id]}</p>}
              {s.generation_source === "ai_auto" && s.status === "draft" && (
                <div className="flex gap-2 mb-2">
                  <button
                    onClick={() => updateScriptStatus(s.id, "approved")}
                    className="inline-flex items-center gap-1 rounded-lg bg-gray-900 text-white text-[11px] font-medium px-2.5 py-1 hover:bg-gray-800 transition-colors"
                  >
                    <Check className="h-3 w-3" /> Approve
                  </button>
                  <button
                    onClick={() => updateScriptStatus(s.id, "archived")}
                    className="text-[11px] text-gray-400 hover:text-gray-600 px-2 py-1"
                  >
                    Dismiss
                  </button>
                </div>
              )}
              {statusErrors[s.id] && <p className="text-[11px] text-red-500 mb-2">{statusErrors[s.id]}</p>}
              {editingScriptId === s.id && editDraft ? (
                <div className="space-y-2 rounded-xl border border-blue-100 bg-blue-50/40 p-3">
                  <input
                    type="text" value={editDraft.hook_line}
                    onChange={(e) => setEditDraft((prev) => (prev ? { ...prev, hook_line: e.target.value } : prev))}
                    placeholder="Hook line"
                    className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                  />
                  {editDraft.shots === null && (
                    <>
                      <textarea
                        value={editDraft.dialogue}
                        onChange={(e) => setEditDraft((prev) => (prev ? { ...prev, dialogue: e.target.value } : prev))}
                        placeholder="Dialogue" rows={2}
                        className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none"
                      />
                      <textarea
                        value={editDraft.scene_direction}
                        onChange={(e) => setEditDraft((prev) => (prev ? { ...prev, scene_direction: e.target.value } : prev))}
                        placeholder="Scene direction" rows={2}
                        className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none"
                      />
                    </>
                  )}
                  {editDraft.shots && editDraft.shots.length > 0 && (
                    <div className="space-y-2">
                      {editDraft.shots.map((shot, i) => (
                        <div key={shot.shot_number} className="rounded-lg border border-gray-200 bg-white p-2 space-y-1">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[10px] text-gray-400 shrink-0">Shot {shot.shot_number}</span>
                            <input
                              type="number" min={1} value={shot.duration_seconds}
                              onChange={(e) => updateEditShotField(i, "duration_seconds", Number(e.target.value) || 1)}
                              className="w-14 rounded-md border border-gray-200 px-1.5 py-1 text-[11px]"
                            />
                            <span className="text-[10px] text-gray-400">s</span>
                            <select
                              value={shot.expression ?? ""}
                              onChange={(e) => updateEditShotField(i, "expression", e.target.value || null)}
                              className="rounded-md border border-gray-200 px-1.5 py-1 text-[11px] flex-1"
                            >
                              <option value="">No expression</option>
                              {EXPRESSION_NAMES.map((name) => <option key={name} value={name}>{name}</option>)}
                            </select>
                          </div>
                          <input
                            type="text" value={shot.visual ?? ""}
                            onChange={(e) => updateEditShotField(i, "visual", e.target.value)}
                            placeholder="Visual — staging, props, positioning"
                            className="w-full rounded-md border border-gray-200 px-1.5 py-1 text-[11px]"
                          />
                          <input
                            type="text" value={shot.action}
                            onChange={(e) => updateEditShotField(i, "action", e.target.value)}
                            placeholder="Action — physical performance"
                            className="w-full rounded-md border border-gray-200 px-1.5 py-1 text-[11px]"
                          />
                          <div className="flex items-center gap-1.5">
                            <input
                              type="text" value={shot.dialogue ?? ""}
                              onChange={(e) => updateEditShotField(i, "dialogue", e.target.value || null)}
                              placeholder="Dialogue"
                              className="flex-1 rounded-md border border-gray-200 px-1.5 py-1 text-[11px]"
                            />
                            <input
                              type="text" value={shot.dialogue_delivery ?? ""}
                              onChange={(e) => updateEditShotField(i, "dialogue_delivery", e.target.value || null)}
                              placeholder="Delivery style"
                              className="w-32 rounded-md border border-gray-200 px-1.5 py-1 text-[11px]"
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => saveEdit(s.id)}
                      disabled={savingEdit}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-[11px] font-medium px-2.5 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
                    >
                      {savingEdit ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                      Save
                    </button>
                    <button onClick={cancelEdit} className="text-[11px] text-gray-400 hover:text-gray-600">
                      Cancel
                    </button>
                  </div>
                  {editError && <p className="text-[11px] text-red-500">{editError}</p>}
                </div>
              ) : (
                <>
                  {s.hook_line && <p className="text-sm font-medium text-gray-900">&quot;{s.hook_line}&quot;</p>}
                  {s.dialogue && <p className="text-sm text-gray-600 mt-1">{s.dialogue}</p>}
                  {s.scene_direction && <p className="text-xs text-gray-400 mt-1 italic">{s.scene_direction}</p>}
                  {s.shots && s.shots.length > 0 && (
                    <ol className="mt-2 space-y-2">
                      {s.shots.map((shot) => (
                        <li key={shot.shot_number} className="text-xs text-gray-600">
                          <span className="text-gray-400">
                            Shot {shot.shot_number} ({shot.duration_seconds}s)
                            {(s.character_variant_ids?.length ?? 0) > 1 && shot.speaker_variant_id && (
                              <> — <span className="font-medium text-gray-700">{variantName(shot.speaker_variant_id)}</span></>
                            )}
                          </span>
                          {shot.visual && (
                            <p className="mt-0.5"><span className="text-gray-400">Visual:</span> {shot.visual}</p>
                          )}
                          <p className="mt-0.5">
                            <span className="text-gray-400">Action:</span> {shot.action}
                            {shot.expression && <span className="text-gray-400"> · {shot.expression}</span>}
                          </p>
                          {shot.dialogue && (
                            <p className="mt-0.5">
                              <span className="text-gray-400">
                                Dialogue{shot.dialogue_delivery ? ` (${shot.dialogue_delivery})` : ""}:
                              </span>{" "}
                              &quot;{shot.dialogue}&quot;
                            </p>
                          )}
                        </li>
                      ))}
                    </ol>
                  )}
                </>
              )}

              <div className="mt-3 pt-3 border-t border-gray-50">
                {bg ? (
                  <div className="flex items-start gap-2.5">
                    {bg.image_url && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={bg.image_url} alt={bg.name} className="h-12 w-12 rounded-lg object-cover shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-gray-700 truncate mb-1">{bg.name}</p>
                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          type="text"
                          value={extraDescByScript[s.id] ?? ""}
                          onChange={(e) => setExtraDescByScript((prev) => ({ ...prev, [s.id]: e.target.value }))}
                          placeholder="Correct or refine the scene before regenerating (optional)"
                          className="flex-1 min-w-[10rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
                        />
                        <select
                          value={bgStyleByScript[s.id] ?? DEFAULT_BACKGROUND_STYLE}
                          onChange={(e) => setBgStyleByScript((prev) => ({ ...prev, [s.id]: e.target.value }))}
                          className="rounded-lg border border-gray-200 px-1.5 py-1.5 text-[11px] shrink-0"
                        >
                          {ART_STYLES.map((style) => (
                            <option key={style.key} value={style.key}>{style.label}</option>
                          ))}
                        </select>
                        <button
                          onClick={() => generateBackground(s.id)}
                          disabled={generating}
                          className="text-[11px] text-blue-500 hover:underline disabled:opacity-50 shrink-0"
                        >
                          {generating ? "Regenerating…" : "Regenerate background"}
                        </button>
                      </div>
                      <p className="text-[10px] text-gray-400 mt-1">
                        {ART_STYLES.find((style) => style.key === (bgStyleByScript[s.id] ?? DEFAULT_BACKGROUND_STYLE))?.hint}
                      </p>
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
                    <select
                      value={bgStyleByScript[s.id] ?? DEFAULT_BACKGROUND_STYLE}
                      onChange={(e) => setBgStyleByScript((prev) => ({ ...prev, [s.id]: e.target.value }))}
                      className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs shrink-0"
                    >
                      {ART_STYLES.map((style) => (
                        <option key={style.key} value={style.key}>{style.label}</option>
                      ))}
                    </select>
                    <button
                      onClick={() => generateBackground(s.id)}
                      disabled={generating || (!hasScene && !(extraDescByScript[s.id] ?? "").trim())}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60 shrink-0"
                    >
                      {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImageIcon className="h-3.5 w-3.5" />}
                      Generate background
                    </button>
                    <p className="w-full text-[10px] text-gray-400">
                      {ART_STYLES.find((style) => style.key === (bgStyleByScript[s.id] ?? DEFAULT_BACKGROUND_STYLE))?.hint}
                    </p>
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

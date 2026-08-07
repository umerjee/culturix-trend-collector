"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, ExternalLink, Clapperboard, ArrowUp, ArrowDown, X, Scissors, Sparkles, Film, RefreshCw, Trash2 } from "lucide-react";
import type { Toon, ToonEpisode, ToonScene, CharacterVariant, ToonScript, ToonBackground } from "@/lib/types";

interface Props {
  brandId: string;
  initialEpisodes: ToonEpisode[];
  initialToons: Toon[];
  variants: CharacterVariant[];
  scripts: ToonScript[];
  backgrounds: ToonBackground[];
}

const STATUS_BADGE_STYLES: Record<ToonEpisode["status"], string> = {
  draft: "bg-gray-100 text-gray-500",
  stitching: "bg-amber-50 text-amber-700",
  ready: "bg-blue-50 text-blue-700",
  failed: "bg-red-50 text-red-600",
  archived: "bg-gray-50 text-gray-400",
};

const SCENE_STATUS_STYLES: Record<ToonScene["status"], string> = {
  idea: "bg-gray-100 text-gray-500",
  generating: "bg-amber-50 text-amber-700",
  ready: "bg-blue-50 text-blue-700",
  failed: "bg-red-50 text-red-600",
};

export default function EpisodeManager({ brandId, initialEpisodes, initialToons, variants, scripts, backgrounds }: Props) {
  const [episodes, setEpisodes] = useState(initialEpisodes.filter((e) => e.status !== "archived"));
  const [toons, setToons] = useState(initialToons);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [attachToonId, setAttachToonId] = useState<Record<string, string>>({});
  const [busyEpisodeId, setBusyEpisodeId] = useState<string | null>(null);
  const [nextIdea, setNextIdea] = useState<Record<string, string>>({});
  const [nextVariantId, setNextVariantId] = useState<Record<string, string>>({});
  const [suggestingNextId, setSuggestingNextId] = useState<string | null>(null);
  const [suggestNextError, setSuggestNextError] = useState<Record<string, string>>({});

  // Scenes are the alternative production path (independent per-scene
  // generation) to the Toon-parts flow above — loaded lazily per episode,
  // not eagerly for every episode on mount.
  const [scenesByEpisode, setScenesByEpisode] = useState<Record<string, ToonScene[]>>({});
  const [scenesLoading, setScenesLoading] = useState<Record<string, boolean>>({});
  const [scenesOpen, setScenesOpen] = useState<Record<string, boolean>>({});
  const [sceneVariantIds, setSceneVariantIds] = useState<Record<string, string[]>>({});
  const [sceneAction, setSceneAction] = useState<Record<string, string>>({});
  const [sceneDialogue, setSceneDialogue] = useState<Record<string, string>>({});
  const [sceneBackgroundId, setSceneBackgroundId] = useState<Record<string, string>>({});
  const [sceneScriptId, setSceneScriptId] = useState<Record<string, string>>({});
  const [busySceneId, setBusySceneId] = useState<string | null>(null);
  const [sceneError, setSceneError] = useState<Record<string, string>>({});

  // A toon already in an episode (this one or another) shouldn't be offered
  // again — episode parts are 1:1 with their episode, not shared.
  const unattachedToons = toons.filter((t) => !t.episode_id);

  function toonById(id: string) {
    return toons.find((t) => t.id === id) ?? null;
  }

  async function refreshEpisode(episodeId: string) {
    const res = await fetch(`/api/culturetoons/episodes/${episodeId}?brand_id=${brandId}`, { cache: "no-store" });
    if (res.ok) {
      const updated = await res.json();
      setEpisodes((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
    }
  }

  // Poll episodes mid-stitch — same shape as ToonManager's own mid-generation poll.
  useEffect(() => {
    const stitching = episodes.filter((e) => e.status === "stitching");
    if (stitching.length === 0) return;
    const interval = setInterval(() => {
      for (const e of stitching) refreshEpisode(e.id);
    }, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [episodes, brandId]);

  async function createEpisode(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      const res = await fetch("/api/culturetoons/episodes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, title: title.trim() || undefined }),
      });
      if (res.ok) {
        const created = await res.json();
        setEpisodes((prev) => [created, ...prev]);
        setTitle("");
      }
    } finally {
      setCreating(false);
    }
  }

  async function attachPart(episodeId: string) {
    const toonId = attachToonId[episodeId];
    if (!toonId) return;
    setBusyEpisodeId(episodeId);
    try {
      const res = await fetch(`/api/culturetoons/episodes/${episodeId}/parts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, toon_id: toonId }),
      });
      if (res.ok) {
        const updated = await res.json();
        setEpisodes((prev) => prev.map((e) => (e.id === episodeId ? updated : e)));
        setToons((prev) => prev.map((t) => (t.id === toonId ? { ...t, episode_id: episodeId } : t)));
        setAttachToonId((prev) => ({ ...prev, [episodeId]: "" }));
      }
    } finally {
      setBusyEpisodeId(null);
    }
  }

  async function suggestNextPart(episodeId: string) {
    const idea = (nextIdea[episodeId] ?? "").trim();
    const variantId = nextVariantId[episodeId] || variants[0]?.id;
    if (!idea || !variantId) return;
    setSuggestingNextId(episodeId);
    setSuggestNextError((prev) => ({ ...prev, [episodeId]: "" }));
    try {
      const res = await fetch(`/api/culturetoons/episodes/${episodeId}/parts/suggest-next`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, idea, character_variant_id: variantId }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setEpisodes((prev) => prev.map((e) => (e.id === episodeId ? data : e)));
        setNextIdea((prev) => ({ ...prev, [episodeId]: "" }));
        // The new part's Toon isn't in `toons` yet (created server-side, not
        // via the usual Toons-tab flow) — refetch so it shows up correctly
        // in the "attach existing toon" picker and Toons tab alike.
        const toonsRes = await fetch(`/api/culturetoons/toons?brand_id=${brandId}`, { cache: "no-store" });
        if (toonsRes.ok) setToons(await toonsRes.json());
      } else {
        setSuggestNextError((prev) => ({ ...prev, [episodeId]: typeof data.detail === "string" ? data.detail : "Suggestion failed" }));
      }
    } finally {
      setSuggestingNextId(null);
    }
  }

  async function detachPart(episodeId: string, toonId: string) {
    setBusyEpisodeId(episodeId);
    try {
      const res = await fetch(`/api/culturetoons/episodes/${episodeId}/parts/${toonId}?brand_id=${brandId}`, { method: "DELETE" });
      if (res.ok) {
        const updated = await res.json();
        setEpisodes((prev) => prev.map((e) => (e.id === episodeId ? updated : e)));
        setToons((prev) => prev.map((t) => (t.id === toonId ? { ...t, episode_id: null, part_order: null } : t)));
      }
    } finally {
      setBusyEpisodeId(null);
    }
  }

  async function movePart(episode: ToonEpisode, index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= episode.parts.length) return;
    const ids = episode.parts.map((p) => p.toon_id);
    [ids[index], ids[target]] = [ids[target], ids[index]];
    setBusyEpisodeId(episode.id);
    try {
      const res = await fetch(`/api/culturetoons/episodes/${episode.id}/parts/reorder`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, toon_ids: ids }),
      });
      if (res.ok) {
        const updated = await res.json();
        setEpisodes((prev) => prev.map((e) => (e.id === episode.id ? updated : e)));
      }
    } finally {
      setBusyEpisodeId(null);
    }
  }

  async function stitch(episodeId: string) {
    setBusyEpisodeId(episodeId);
    try {
      const res = await fetch(`/api/culturetoons/episodes/${episodeId}/stitch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      if (res.ok) {
        setEpisodes((prev) => prev.map((e) => (e.id === episodeId ? { ...e, status: "stitching", generation_error: null } : e)));
      } else {
        const data = await res.json().catch(() => ({}));
        setEpisodes((prev) => prev.map((e) => (e.id === episodeId ? { ...e, generation_error: typeof data.detail === "string" ? data.detail : "Stitch failed to start" } : e)));
      }
    } finally {
      setBusyEpisodeId(null);
    }
  }

  async function generateClips(episodeId: string) {
    setBusyEpisodeId(episodeId);
    try {
      const res = await fetch(`/api/culturetoons/episodes/${episodeId}/generate-clips`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      if (res.ok) {
        // Clip generation doesn't flip episode.status, so poll once shortly
        // after rather than adding a whole separate "generating" state.
        setTimeout(() => refreshEpisode(episodeId), 6000);
      }
    } finally {
      setBusyEpisodeId(null);
    }
  }

  async function loadScenes(episodeId: string) {
    setScenesLoading((prev) => ({ ...prev, [episodeId]: true }));
    try {
      const res = await fetch(`/api/culturetoons/episodes/${episodeId}/scenes?brand_id=${brandId}`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setScenesByEpisode((prev) => ({ ...prev, [episodeId]: data }));
      }
    } finally {
      setScenesLoading((prev) => ({ ...prev, [episodeId]: false }));
    }
  }

  function toggleScenes(episodeId: string) {
    const opening = !scenesOpen[episodeId];
    setScenesOpen((prev) => ({ ...prev, [episodeId]: opening }));
    if (opening && !scenesByEpisode[episodeId]) loadScenes(episodeId);
  }

  // Poll scenes mid-generation, same shape as the episode stitching poll above.
  useEffect(() => {
    const openEpisodeIds = Object.keys(scenesOpen).filter((id) => scenesOpen[id]);
    const generating = openEpisodeIds.filter((id) => (scenesByEpisode[id] ?? []).some((s) => s.status === "generating"));
    if (generating.length === 0) return;
    const interval = setInterval(() => {
      for (const id of generating) loadScenes(id);
    }, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenesOpen, scenesByEpisode, brandId]);

  async function createScene(episodeId: string) {
    setBusyEpisodeId(episodeId);
    try {
      const res = await fetch(`/api/culturetoons/episodes/${episodeId}/scenes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          character_variant_ids: sceneVariantIds[episodeId] ?? [],
          action: sceneAction[episodeId]?.trim() || undefined,
          dialogue: sceneDialogue[episodeId]?.trim() || undefined,
          background_id: sceneBackgroundId[episodeId] || undefined,
        }),
      });
      if (res.ok) {
        const created = await res.json();
        setScenesByEpisode((prev) => ({ ...prev, [episodeId]: [...(prev[episodeId] ?? []), created] }));
        setSceneAction((prev) => ({ ...prev, [episodeId]: "" }));
        setSceneDialogue((prev) => ({ ...prev, [episodeId]: "" }));
        setSceneBackgroundId((prev) => ({ ...prev, [episodeId]: "" }));
      }
    } finally {
      setBusyEpisodeId(null);
    }
  }

  async function createScenesFromScript(episodeId: string) {
    const scriptId = sceneScriptId[episodeId];
    if (!scriptId) return;
    setBusyEpisodeId(episodeId);
    try {
      const res = await fetch(`/api/culturetoons/episodes/${episodeId}/scenes/from-script`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, script_id: scriptId }),
      });
      const data = await res.json().catch(() => ([]));
      if (res.ok) {
        setScenesByEpisode((prev) => ({ ...prev, [episodeId]: [...(prev[episodeId] ?? []), ...data] }));
        setScenesOpen((prev) => ({ ...prev, [episodeId]: true }));
      } else {
        setSceneError((prev) => ({ ...prev, [episodeId]: typeof data.detail === "string" ? data.detail : "Couldn't build scenes from that script" }));
      }
    } finally {
      setBusyEpisodeId(null);
    }
  }

  async function generateScene(episodeId: string, sceneId: string) {
    setBusySceneId(sceneId);
    setSceneError((prev) => ({ ...prev, [sceneId]: "" }));
    try {
      const res = await fetch(`/api/culturetoons/scenes/${sceneId}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setScenesByEpisode((prev) => ({
          ...prev,
          [episodeId]: (prev[episodeId] ?? []).map((s) => (s.id === sceneId ? { ...s, status: "generating", generation_error: null } : s)),
        }));
      } else {
        setSceneError((prev) => ({ ...prev, [sceneId]: typeof data.detail === "string" ? data.detail : "Couldn't start generation" }));
      }
    } finally {
      setBusySceneId(null);
    }
  }

  async function deleteScene(episodeId: string, sceneId: string) {
    setBusySceneId(sceneId);
    try {
      const res = await fetch(`/api/culturetoons/scenes/${sceneId}?brand_id=${brandId}`, { method: "DELETE" });
      if (res.ok) {
        setScenesByEpisode((prev) => ({ ...prev, [episodeId]: (prev[episodeId] ?? []).filter((s) => s.id !== sceneId) }));
      }
    } finally {
      setBusySceneId(null);
    }
  }

  async function assembleFromScenes(episodeId: string) {
    setBusyEpisodeId(episodeId);
    try {
      const res = await fetch(`/api/culturetoons/episodes/${episodeId}/assemble-scenes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      if (res.ok) {
        setEpisodes((prev) => prev.map((e) => (e.id === episodeId ? { ...e, status: "stitching", generation_error: null } : e)));
      } else {
        const data = await res.json().catch(() => ({}));
        setEpisodes((prev) => prev.map((e) => (e.id === episodeId ? { ...e, generation_error: typeof data.detail === "string" ? data.detail : "Assembly failed to start" } : e)));
      }
    } finally {
      setBusyEpisodeId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Step 1 · Create an episode</h3>
        <p className="text-xs text-gray-400 mt-0.5">
          Optional — a longer story stitched from multiple pieces. Two ways to build one, pick per
          episode: <strong>Parts</strong> (below — generate each part as a normal toon in the Toons
          tab first, then assemble them here) or <strong>Scenes</strong> (inside each episode card —
          generate and regenerate each short beat independently, without redoing the whole story if
          one goes wrong). Parts is simpler for a short story; Scenes is better once episodes get
          longer or you expect to redo individual beats.
        </p>
      </div>

      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <form onSubmit={createEpisode} className="flex flex-wrap gap-2 items-center">
          <input
            type="text" value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder="Episode title, e.g. “Kumar's Big Day”"
            className="flex-1 min-w-[10rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
          />
          <button
            type="submit"
            disabled={creating}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
          >
            {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            New episode
          </button>
        </form>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-900">Step 2 · Your episodes</h3>
        {episodes.length === 0 && (
          <p className="text-xs text-gray-400">
            No episodes yet — optional. Most toons work fine standalone; come back here once you want
            to stitch a few of them (or independently-generated scenes) into a longer story.
          </p>
        )}
        {episodes.map((ep) => {
          const readyParts = ep.parts.filter((p) => p.has_raw_video).length;
          const canStitch = ep.parts.length >= 2 && readyParts === ep.parts.length && ep.status !== "stitching";
          const busy = busyEpisodeId === ep.id;
          return (
            <div key={ep.id} className="rounded-2xl bg-white border border-gray-100 p-4">
              <div className="flex items-start justify-between gap-2 mb-2">
                <span className="text-sm font-medium text-gray-900">{ep.title || "Untitled episode"}</span>
                <span className={`text-[10px] uppercase tracking-wide font-medium rounded-full px-2 py-1 shrink-0 ${STATUS_BADGE_STYLES[ep.status]}`}>
                  {ep.status}
                </span>
              </div>

              <ol className="space-y-1.5">
                {ep.parts.length === 0 && (
                  <p className="text-xs text-gray-400">
                    No parts attached yet — attach an existing toon below, or use Scenes instead (further down this card).
                  </p>
                )}
                {ep.parts.map((p, i) => (
                  <li key={p.toon_id} className="flex items-center gap-2 text-xs bg-gray-50 rounded-lg px-2.5 py-1.5">
                    <span className="text-gray-400 w-4 shrink-0">{i + 1}.</span>
                    <span className="flex-1 truncate">{p.title || toonById(p.toon_id)?.title || "Untitled toon"}</span>
                    <span className={p.has_raw_video ? "text-blue-600" : "text-amber-600"}>
                      {p.has_raw_video ? "ready" : p.status}
                    </span>
                    <button onClick={() => movePart(ep, i, -1)} disabled={i === 0 || busy} className="text-gray-400 hover:text-gray-700 disabled:opacity-30">
                      <ArrowUp className="h-3 w-3" />
                    </button>
                    <button onClick={() => movePart(ep, i, 1)} disabled={i === ep.parts.length - 1 || busy} className="text-gray-400 hover:text-gray-700 disabled:opacity-30">
                      <ArrowDown className="h-3 w-3" />
                    </button>
                    <button onClick={() => detachPart(ep.id, p.toon_id)} disabled={busy} className="text-gray-400 hover:text-red-500 disabled:opacity-30">
                      <X className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ol>

              <div className="flex flex-wrap gap-2 items-center mt-2">
                <select
                  value={attachToonId[ep.id] ?? ""}
                  onChange={(e) => setAttachToonId((prev) => ({ ...prev, [ep.id]: e.target.value }))}
                  className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs min-w-[10rem]"
                >
                  <option value="">Attach an existing toon…</option>
                  {unattachedToons.map((t) => (
                    <option key={t.id} value={t.id}>{t.title || t.id.slice(0, 8)}{t.raw_video_url ? "" : " — not generated yet"}</option>
                  ))}
                </select>
                <button
                  onClick={() => attachPart(ep.id)}
                  disabled={!attachToonId[ep.id] || busy}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
                >
                  <Plus className="h-3.5 w-3.5" /> Attach
                </button>
              </div>

              {ep.parts.length > 0 && (
                <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 mt-2">
                  <span className="text-xs font-semibold text-gray-700">Suggest the next part with AI</span>
                  <p className="text-[11px] text-gray-400 mt-0.5 mb-1.5">
                    Grounded in what already happened in this episode — describe what should happen next.
                  </p>
                  <div className="flex flex-wrap gap-2 items-center">
                    <input
                      type="text"
                      value={nextIdea[ep.id] ?? ""}
                      onChange={(e) => setNextIdea((prev) => ({ ...prev, [ep.id]: e.target.value }))}
                      placeholder={`E.g. "Mom walks in with even more food"`}
                      className="flex-1 min-w-[10rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                    />
                    <select
                      value={nextVariantId[ep.id] ?? variants[0]?.id ?? ""}
                      onChange={(e) => setNextVariantId((prev) => ({ ...prev, [ep.id]: e.target.value }))}
                      className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
                    >
                      {variants.length === 0 && <option value="">No characters yet</option>}
                      {variants.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                    </select>
                    <button
                      onClick={() => suggestNextPart(ep.id)}
                      disabled={!(nextIdea[ep.id] ?? "").trim() || suggestingNextId === ep.id}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
                    >
                      {suggestingNextId === ep.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      Suggest
                    </button>
                  </div>
                  {suggestNextError[ep.id] && <p className="text-[11px] text-red-500 mt-1">{suggestNextError[ep.id]}</p>}
                </div>
              )}

              <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 mt-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-semibold text-gray-700">Stitch into one video</span>
                  <button
                    onClick={() => stitch(ep.id)}
                    disabled={!canStitch || busy}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
                  >
                    {ep.status === "stitching" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Clapperboard className="h-3.5 w-3.5" />}
                    {ep.final_video_url ? "Re-stitch" : "Stitch episode"}
                  </button>
                </div>
                {!canStitch && ep.status !== "stitching" && (
                  <p className="text-[11px] text-gray-400">
                    {ep.parts.length < 2
                      ? "Attach at least 2 parts to stitch an episode."
                      : `${ep.parts.length - readyParts} part(s) still need their video generated (in the Toons tab) before this can stitch.`}
                  </p>
                )}
                {ep.status === "stitching" && <p className="text-[11px] text-amber-600">Stitching — this can take a few minutes.</p>}
                {ep.generation_error && <p className="text-[11px] text-red-500 mt-1">{ep.generation_error}</p>}
                {ep.final_video_url && (
                  <div className="mt-2 space-y-2">
                    <a href={ep.final_video_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-blue-500 hover:underline">
                      <ExternalLink className="h-3 w-3" /> View stitched episode
                    </a>
                    <div>
                      <button
                        onClick={() => generateClips(ep.id)}
                        disabled={busy}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 text-gray-700 text-xs font-medium px-3 py-1.5 hover:border-blue-300 hover:text-blue-600 transition-colors disabled:opacity-60"
                      >
                        <Scissors className="h-3.5 w-3.5" />
                        {ep.clip_video_urls.length > 0 ? "Regenerate social clips" : "Generate social clips"}
                      </button>
                    </div>
                    {ep.clip_video_urls.length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {ep.clip_video_urls.map((url, i) => (
                          <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-blue-500 hover:underline">
                            <ExternalLink className="h-3 w-3" /> Clip {i + 1}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 mt-3">
                <button
                  onClick={() => toggleScenes(ep.id)}
                  className="flex items-center justify-between w-full text-left"
                >
                  <span className="text-xs font-semibold text-gray-700">
                    Scenes — independent generation {(scenesByEpisode[ep.id]?.length ?? 0) > 0 && `(${scenesByEpisode[ep.id]!.length})`}
                  </span>
                  <span className="text-[10px] text-blue-600">{scenesOpen[ep.id] ? "Hide" : "Show"}</span>
                </button>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  An alternative to parts above: each scene generates and regenerates on its own — a failed
                  or disappointing scene can be redone without touching the rest of the episode.
                </p>

                {scenesOpen[ep.id] && (
                  <div className="mt-2 space-y-2">
                    {scenesLoading[ep.id] && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" />}

                    {(scenesByEpisode[ep.id] ?? []).map((scene) => (
                      <div key={scene.id} className="rounded-lg bg-white border border-gray-100 p-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium text-gray-700">Scene {scene.scene_number}</span>
                          <span className={`text-[10px] uppercase tracking-wide font-medium rounded-full px-2 py-0.5 shrink-0 ${SCENE_STATUS_STYLES[scene.status]}`}>
                            {scene.status}
                          </span>
                        </div>
                        {scene.action && <p className="text-[11px] text-gray-600 mt-1">{scene.action}</p>}
                        {scene.dialogue && <p className="text-[11px] text-gray-400 italic">&ldquo;{scene.dialogue}&rdquo;</p>}
                        <div className="flex flex-wrap items-center gap-2 mt-1.5">
                          <button
                            onClick={() => generateScene(ep.id, scene.id)}
                            disabled={!scene.character_variant_ids.length || scene.status === "generating" || busySceneId === scene.id}
                            className="inline-flex items-center gap-1 rounded-lg bg-gray-900 text-white text-[11px] font-medium px-2.5 py-1 hover:bg-gray-800 transition-colors disabled:opacity-60"
                          >
                            {scene.status === "generating" ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                            {scene.video_url ? "Regenerate" : "Generate"}
                          </button>
                          {scene.video_url && (
                            <a href={scene.video_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[11px] text-blue-500 hover:underline">
                              <ExternalLink className="h-3 w-3" /> View
                            </a>
                          )}
                          <button
                            onClick={() => deleteScene(ep.id, scene.id)}
                            disabled={busySceneId === scene.id}
                            className="inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-red-500 disabled:opacity-40 ml-auto"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                        {!scene.character_variant_ids.length && (
                          <p className="text-[10px] text-amber-600 mt-1">Assign a character to this scene before generating.</p>
                        )}
                        {scene.generation_error && <p className="text-[11px] text-red-500 mt-1">{scene.generation_error}</p>}
                        {sceneError[scene.id] && <p className="text-[11px] text-red-500 mt-1">{sceneError[scene.id]}</p>}
                      </div>
                    ))}

                    <div className="rounded-lg border border-dashed border-gray-200 p-2.5 space-y-1.5">
                      <div className="flex flex-wrap gap-2 items-center">
                        <select
                          multiple
                          value={sceneVariantIds[ep.id] ?? []}
                          onChange={(e) => setSceneVariantIds((prev) => ({
                            ...prev, [ep.id]: Array.from(e.target.selectedOptions, (o) => o.value),
                          }))}
                          className="rounded-lg border border-gray-200 px-2 py-1 text-xs min-w-[8rem] h-16"
                        >
                          {variants.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                        </select>
                        <div className="flex-1 min-w-[10rem] space-y-1.5">
                          <input
                            type="text" value={sceneAction[ep.id] ?? ""}
                            onChange={(e) => setSceneAction((prev) => ({ ...prev, [ep.id]: e.target.value }))}
                            placeholder="What happens in this scene…"
                            className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                          />
                          <input
                            type="text" value={sceneDialogue[ep.id] ?? ""}
                            onChange={(e) => setSceneDialogue((prev) => ({ ...prev, [ep.id]: e.target.value }))}
                            placeholder="Dialogue (optional)"
                            className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                          />
                          <select
                            value={sceneBackgroundId[ep.id] ?? ""}
                            onChange={(e) => setSceneBackgroundId((prev) => ({ ...prev, [ep.id]: e.target.value }))}
                            className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                          >
                            <option value="">No location</option>
                            {backgrounds.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                          </select>
                        </div>
                        <button
                          onClick={() => createScene(ep.id)}
                          disabled={busy}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60 self-start"
                        >
                          <Plus className="h-3.5 w-3.5" /> Add scene
                        </button>
                      </div>

                      {scripts.length > 0 && (
                        <div className="flex flex-wrap gap-2 items-center pt-1.5 border-t border-gray-100">
                          <span className="text-[11px] text-gray-400">or build scenes from a script:</span>
                          <select
                            value={sceneScriptId[ep.id] ?? ""}
                            onChange={(e) => setSceneScriptId((prev) => ({ ...prev, [ep.id]: e.target.value }))}
                            className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs min-w-[10rem]"
                          >
                            <option value="">Choose a script…</option>
                            {scripts.map((s) => (
                              <option key={s.id} value={s.id}>{s.hook_line || s.id.slice(0, 8)}</option>
                            ))}
                          </select>
                          <button
                            onClick={() => createScenesFromScript(ep.id)}
                            disabled={!sceneScriptId[ep.id] || busy}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 text-gray-700 text-xs font-medium px-3 py-1.5 hover:border-blue-300 hover:text-blue-600 transition-colors disabled:opacity-60"
                          >
                            <Sparkles className="h-3.5 w-3.5" /> Build scenes
                          </button>
                        </div>
                      )}
                      {sceneError[ep.id] && <p className="text-[11px] text-red-500">{sceneError[ep.id]}</p>}
                    </div>

                    {(scenesByEpisode[ep.id] ?? []).some((s) => s.status === "ready") && (
                      <button
                        onClick={() => assembleFromScenes(ep.id)}
                        disabled={busy || ep.status === "stitching"}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
                      >
                        {ep.status === "stitching" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Film className="h-3.5 w-3.5" />}
                        {ep.final_video_url ? "Re-assemble episode from scenes" : "Assemble episode from scenes"}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, ExternalLink, Clapperboard, ArrowUp, ArrowDown, X, Scissors, Sparkles } from "lucide-react";
import type { Toon, ToonEpisode, CharacterVariant } from "@/lib/types";

interface Props {
  brandId: string;
  initialEpisodes: ToonEpisode[];
  initialToons: Toon[];
  variants: CharacterVariant[];
}

const STATUS_BADGE_STYLES: Record<ToonEpisode["status"], string> = {
  draft: "bg-gray-100 text-gray-500",
  stitching: "bg-amber-50 text-amber-700",
  ready: "bg-blue-50 text-blue-700",
  failed: "bg-red-50 text-red-600",
  archived: "bg-gray-50 text-gray-400",
};

export default function EpisodeManager({ brandId, initialEpisodes, initialToons, variants }: Props) {
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

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Step 1 · Create an episode</h3>
        <p className="text-xs text-gray-400 mt-0.5">
          A longer story stitched from several toons in order — generate each part as a normal
          toon in the Toons tab first, then assemble them here.
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
        {episodes.length === 0 && <p className="text-xs text-gray-400">No episodes yet.</p>}
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
                {ep.parts.length === 0 && <p className="text-xs text-gray-400">No parts attached yet.</p>}
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
            </div>
          );
        })}
      </div>
    </div>
  );
}

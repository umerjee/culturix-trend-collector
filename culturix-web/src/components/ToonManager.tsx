"use client";

import { useEffect, useState } from "react";
import {
  Plus, Loader2, ExternalLink, Clapperboard, Send, ShieldCheck, ShieldAlert, AlertTriangle,
  ArrowRight, ChevronDown, ChevronRight, CheckCircle2,
} from "lucide-react";
import type { Toon, ToonScript, CharacterVariant, ToonBackground, ConnectedAccount, ToonPost } from "@/lib/types";
import { CONNECTABLE_PLATFORMS } from "@/lib/types";
import ConnectedAccountsPanel from "@/components/ConnectedAccountsPanel";
import InfoTooltip from "@/components/ui/Tooltip";

interface Props {
  brandId: string;
  brandName: string;
  initialToons: Toon[];
  scripts: ToonScript[];
  variants: CharacterVariant[];
  backgrounds: ToonBackground[];
  // Jumps the parent workspace to the Characters tab with this variant
  // pre-selected — lets the "not registered yet" blocker below take the
  // user straight to the fix instead of just naming where to find it.
  onJumpToVariant: (variantId: string) => void;
}

const STATUSES: Toon["status"][] = ["idea", "animating", "ready", "posted", "archived", "failed"];
// "animating" is system-managed — only the real Generate video flow (which
// also launches the actual background Kling call) should ever set it.
// Picking it manually from this dropdown used to set the status flag with
// nothing behind it: no kling_task_id, no error, no background task —
// just a permanently "stuck" spinner with no way forward (confirmed live:
// a toon sat in "animating" for hours with an unregistered character and
// no Kling call ever made). Still rendered as an option so the dropdown
// can display it as the current value while a real generation is in
// flight, but disabled so it can't be freely (re-)selected.
const MANUALLY_UNSELECTABLE_STATUSES: Toon["status"][] = ["animating"];

const STATUS_BADGE_STYLES: Record<Toon["status"], string> = {
  idea: "bg-gray-100 text-gray-500",
  animating: "bg-amber-50 text-amber-700",
  ready: "bg-blue-50 text-blue-700",
  posted: "bg-green-50 text-green-700",
  archived: "bg-gray-50 text-gray-400",
  failed: "bg-red-50 text-red-600",
};

export default function ToonManager({ brandId, brandName, initialToons, scripts, variants, backgrounds, onJumpToVariant }: Props) {
  const [toons, setToons] = useState(initialToons.filter((t) => t.status !== "archived"));
  const [variantId, setVariantId] = useState(variants[0]?.id ?? "");
  const [scriptId, setScriptId] = useState(scripts[0]?.id ?? "");
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [generatingId, setGeneratingId] = useState<string | null>(null);

  const [connectedAccounts, setConnectedAccounts] = useState<ConnectedAccount[]>([]);
  const [postsByToon, setPostsByToon] = useState<Record<string, ToonPost[]>>({});
  const [publishPlatformByToon, setPublishPlatformByToon] = useState<Record<string, string>>({});
  const [publishingId, setPublishingId] = useState<string | null>(null);

  const connectablePlatforms = connectedAccounts.filter((a) => a.status === "active");

  async function loadPosts(toonId: string) {
    const res = await fetch(`/api/culturetoons/toons/${toonId}/posts?brand_id=${brandId}`, { cache: "no-store" });
    if (!res.ok) return;
    const posts: ToonPost[] = await res.json();
    const wasPending = (postsByToon[toonId] ?? []).some((p) => p.status === "pending");
    setPostsByToon((prev) => ({ ...prev, [toonId]: posts }));
    // publish_toon_and_record syncs Toon.status/platform on success — re-sync
    // this component's local toon once a publish leaves "pending" so the
    // status dropdown above stops showing a stale "ready".
    if (wasPending && posts.length > 0 && posts[0].status !== "pending") {
      const toonRes = await fetch(`/api/culturetoons/toons/${toonId}?brand_id=${brandId}`, { cache: "no-store" });
      if (toonRes.ok) {
        const updated = await toonRes.json();
        setToons((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      }
    }
  }

  useEffect(() => {
    for (const t of toons) {
      if (t.status === "ready" || t.status === "posted") loadPosts(t.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, toons.length]);

  // Poll toon posts still mid-publish.
  useEffect(() => {
    const pendingToonIds = Object.entries(postsByToon)
      .filter(([, posts]) => posts.some((p) => p.status === "pending"))
      .map(([id]) => id);
    if (pendingToonIds.length === 0) return;
    const interval = setInterval(() => {
      for (const id of pendingToonIds) loadPosts(id);
    }, 4000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [postsByToon]);

  async function publishToon(toonId: string) {
    const platform = publishPlatformByToon[toonId];
    if (!platform) return;
    setPublishingId(toonId);
    try {
      const res = await fetch(`/api/culturetoons/toons/${toonId}/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, platform }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setPostsByToon((prev) => ({ ...prev, [toonId]: [data, ...(prev[toonId] ?? [])] }));
      } else {
        setPostsByToon((prev) => ({
          ...prev,
          [toonId]: [{ id: `error-${Date.now()}`, toon_id: toonId, brand_id: brandId, platform, post_url: null,
            platform_post_id: null, status: "failed", latest_views: null, latest_likes: null, latest_comments: null,
            latest_shares: null, last_fetched_at: null, error: typeof data.detail === "string" ? data.detail : "Publish failed",
            created_at: new Date().toISOString(), posted_at: null }, ...(prev[toonId] ?? [])],
        }));
      }
    } finally {
      setPublishingId(null);
    }
  }

  const [advancedOpenId, setAdvancedOpenId] = useState<string | null>(null);
  const [historyOpenId, setHistoryOpenId] = useState<string | null>(null);

  function variantName(id: string) {
    return variants.find((v) => v.id === id)?.name ?? "—";
  }

  function scriptFor(id: string) {
    return scripts.find((s) => s.id === id) ?? null;
  }

  function variantFor(id: string) {
    return variants.find((v) => v.id === id) ?? null;
  }

  // A custom title always wins; absent one, the script's hook line is far
  // more useful for telling apart several toons of the same character than
  // repeating the character's name twice (confirmed live: three toon cards
  // all rendered as "John John" with nothing else to tell them apart).
  function toonHeadline(t: Toon) {
    if (t.title) return t.title;
    const script = scriptFor(t.script_id);
    return script?.hook_line || script?.dialogue || "Untitled toon";
  }

  function pickClip(toonId: string, url: string) {
    updateToon(toonId, { final_video_url: url });
  }

  // A script that came from "Suggest a script" already carries its own
  // cast (character_variant_id as primary, character_variant_ids as the
  // full multi-character list) — re-picking "a" character independently
  // of that, from a dropdown of the whole brand's roster, was confusing
  // and redundant (confirmed live: "the script already has three
  // characters... why would I have to pick characters again"). The actual
  // generation cast always comes from the script (see
  // generate_video_for_toon's cast_ids resolution) — this field is only a
  // fallback for scripts with no cast of their own (manual scripts with no
  // character chosen), so keep it in sync with the script's own primary
  // character whenever one exists, rather than leaving it independently
  // editable.
  useEffect(() => {
    const script = scriptFor(scriptId);
    if (script?.character_variant_id) setVariantId(script.character_variant_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptId]);

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
        // The endpoint returns {"status": "generation_started"} — a note
        // about the REQUEST, not a Toon field — after backgrounding the
        // real work. Spreading that response onto the toon used to
        // overwrite toon.status with that literal string, which matched
        // neither "animating" nor anything the status dropdown recognizes.
        // That silently broke the mid-generation polling effect below (it
        // only watches for status === "animating") and the "Generating…"
        // banner (same condition), leaving the user with zero feedback and
        // no way to ever see completion — confirmed live: "I have no
        // status it just left me in the open". The backend already flips
        // status to "animating" server-side before returning; mirror that
        // here instead of trusting the response shape.
        setToons((prev) => prev.map((t) => (t.id === id ? { ...t, status: "animating", generation_error: null } : t)));
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
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Step 1 · Connect accounts</h3>
        <p className="text-xs text-gray-400 mb-3">Where this brand's finished toons actually get published.</p>
        <ConnectedAccountsPanel
          brandId={brandId}
          brandName={brandName}
          onAccountsLoaded={setConnectedAccounts}
        />
      </div>

      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Step 2 · Plan a new toon</h3>
        <form onSubmit={createToon} className="flex flex-wrap gap-2 items-center">
          <select value={scriptId} onChange={(e) => setScriptId(e.target.value)} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs min-w-[10rem]">
            {scripts.length === 0 && <option value="">No scripts yet</option>}
            {scripts.map((s) => <option key={s.id} value={s.id}>{s.hook_line || s.dialogue || s.id.slice(0, 8)}</option>)}
          </select>
          {scriptFor(scriptId)?.character_variant_id ? (
            // The script already declares its own cast — generation uses
            // that, not this field — so just show who it is instead of
            // asking the user to pick a character again.
            <span className="rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs text-gray-500">
              Cast: {(scriptFor(scriptId)?.character_variant_ids?.length
                ? scriptFor(scriptId)!.character_variant_ids
                : [variantId]
              ).map((id) => variantName(id)).join(", ")}
            </span>
          ) : (
            <select value={variantId} onChange={(e) => setVariantId(e.target.value)} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs">
              {variants.length === 0 && <option value="">No characters yet</option>}
              {variants.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}{v.element_status !== "ready" ? " — not registered yet" : ""}
                </option>
              ))}
            </select>
          )}
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
        <h3 className="text-sm font-semibold text-gray-900">Step 3 · Your toons</h3>
        {toons.length === 0 && (
          <p className="text-xs text-gray-400">
            No toons yet — pick a script and character above, then &quot;Add toon&quot; to plan your first one.
          </p>
        )}
        {toons.map((t) => {
          const script = scriptFor(t.script_id);
          const variant = variantFor(t.character_variant_id);
          const canGenerate = !!script?.shots?.length && variant?.element_status === "ready";
          const generating = generatingId === t.id || t.status === "animating";
          const advancedOpen = advancedOpenId === t.id;
          return (
            <div key={t.id} className="rounded-2xl bg-white border border-gray-100 p-4">
              <div className="flex flex-wrap items-start justify-between gap-2 mb-2">
                <div>
                  <span className="text-sm font-medium text-gray-900">{toonHeadline(t)}</span>
                  <div className="text-xs text-gray-400 mt-0.5">
                    {variantName(t.character_variant_id)}
                    {t.background_id && backgrounds.find((bg) => bg.id === t.background_id) && (
                      <> · {backgrounds.find((bg) => bg.id === t.background_id)?.name}</>
                    )}
                  </div>
                </div>
                <span className={`text-[10px] uppercase tracking-wide font-medium rounded-full px-2 py-1 shrink-0 ${STATUS_BADGE_STYLES[t.status]}`}>
                  {t.status}
                </span>
              </div>

              {!t.background_id && (
                <select
                  value=""
                  onChange={(e) => updateToon(t.id, { background_id: e.target.value || null })}
                  className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs mb-2"
                >
                  <option value="">No background chosen (optional)</option>
                  {backgrounds.map((bg) => <option key={bg.id} value={bg.id}>{bg.name}</option>)}
                </select>
              )}

              <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 mt-1">
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
                  <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-100 px-2.5 py-2 mt-1">
                    <AlertTriangle className="h-3.5 w-3.5 text-amber-500 mt-0.5 shrink-0" />
                    {!script?.shots?.length ? (
                      <p className="text-xs text-amber-700">
                        This script has no AI-generated shots yet. Go to the Scripts tab and suggest one
                        from a trend or your own idea — a manually-written script can&apos;t drive video generation.
                      </p>
                    ) : (
                      <div className="flex-1">
                        <p className="text-xs text-amber-700">
                          {variantName(t.character_variant_id)} isn&apos;t registered with Kling yet — that&apos;s a
                          required one-time step before any video can be generated for this character.
                        </p>
                        <button
                          onClick={() => onJumpToVariant(t.character_variant_id)}
                          className="inline-flex items-center gap-1 text-xs font-medium text-amber-700 hover:text-amber-900 mt-1"
                        >
                          Register {variantName(t.character_variant_id)} now <ArrowRight className="h-3 w-3" />
                        </button>
                      </div>
                    )}
                  </div>
                )}
                {generating && (
                  <p className="flex items-center gap-1.5 text-[11px] text-amber-600 mt-1">
                    <Loader2 className="h-3 w-3 animate-spin" /> Generating — this can take a few minutes. Feel free to
                    switch tabs; it&apos;ll still be running when you come back.
                  </p>
                )}
                {t.generation_error && <p className="text-[11px] text-red-500 mt-1">{t.generation_error}</p>}
                {t.clip_video_urls && t.clip_video_urls.length > 0 && (
                  <div className="mt-2">
                    <p className="text-[11px] text-gray-500 mb-1.5">
                      {t.final_video_url ? "Pick a different candidate clip, or keep the one selected below:" : "Pick which candidate clip to use:"}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {t.clip_video_urls.map((url, i) => {
                        const selected = t.final_video_url === url;
                        return (
                          <div key={url} className={`flex items-center gap-1.5 rounded-lg border px-2 py-1.5 ${selected ? "border-blue-300 bg-blue-50" : "border-gray-200 bg-white"}`}>
                            <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-blue-500 hover:underline">
                              <ExternalLink className="h-3 w-3" /> Clip {i + 1}
                            </a>
                            {selected ? (
                              <span className="inline-flex items-center gap-1 text-xs text-blue-600 font-medium">
                                <CheckCircle2 className="h-3 w-3" /> Selected
                              </span>
                            ) : (
                              <button onClick={() => pickClip(t.id, url)} className="text-xs text-gray-500 hover:text-gray-800">
                                Use this
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              {t.final_video_url && (
                <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 mt-3">
                  <span className="text-xs font-semibold text-gray-700">Publish</span>
                  {t.publish_recommended === false && t.qa_results && (
                    <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-100 px-2.5 py-2 mt-1.5">
                      <AlertTriangle className="h-3.5 w-3.5 text-amber-500 mt-0.5 shrink-0" />
                      <div className="flex-1">
                        <p className="text-xs text-amber-700 flex items-start gap-1">
                          <span>
                            QA flagged this toon (overall {t.qa_results.overall_score}/100 — comedy {t.qa_results.comedy_score},
                            cultural {t.qa_results.cultural_score}, technical {t.qa_results.technical_score}). Review before publishing:
                          </span>
                          <InfoTooltip text="Each score is 0-100. Technical checks things like resolution and duration automatically; comedy and cultural are AI-judged. Flagged just means 'review before posting' — you can still publish anyway if you disagree." />
                        </p>
                        {t.qa_results.issues.length > 0 && (
                          <ul className="mt-1 space-y-0.5">
                            {t.qa_results.issues.map((issue, i) => (
                              <li key={i} className="text-[11px] text-amber-600">· {issue}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  )}
                  <div className="flex flex-wrap gap-2 items-center mt-1.5">
                    <select
                      value={publishPlatformByToon[t.id] ?? connectablePlatforms[0]?.platform ?? ""}
                      onChange={(e) => setPublishPlatformByToon((prev) => ({ ...prev, [t.id]: e.target.value }))}
                      className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
                    >
                      {connectablePlatforms.length === 0 && <option value="">No connected accounts yet</option>}
                      {connectablePlatforms.map((a) => (
                        <option key={a.platform} value={a.platform}>
                          {CONNECTABLE_PLATFORMS.find((p) => p.key === a.platform)?.display ?? a.platform}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => publishToon(t.id)}
                      disabled={connectablePlatforms.length === 0 || publishingId === t.id}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
                    >
                      {publishingId === t.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                      Publish
                    </button>
                  </div>
                  {connectablePlatforms.length === 0 && (
                    <p className="text-[11px] text-gray-400 mt-1.5">Connect an account above to publish directly from here.</p>
                  )}
                  {(postsByToon[t.id] ?? []).length > 0 && (
                    <div className="space-y-1.5 mt-2">
                      {(postsByToon[t.id] ?? []).map((p) => (
                        <div key={p.id} className="flex items-center gap-1.5 text-[11px]">
                          {p.status === "pending" && <Loader2 className="h-3 w-3 animate-spin text-amber-500 shrink-0" />}
                          {p.status === "tracked" && <ShieldCheck className="h-3 w-3 text-green-600 shrink-0" />}
                          {(p.status === "failed" || p.status === "needs_reconnect") && <ShieldAlert className="h-3 w-3 text-red-500 shrink-0" />}
                          <span className="text-gray-500 capitalize">{p.platform}</span>
                          {p.status === "pending" && <span className="text-amber-600">publishing…</span>}
                          {p.status === "tracked" && p.post_url && (
                            <a href={p.post_url} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">
                              view post
                            </a>
                          )}
                          {p.status === "tracked" && typeof p.latest_views === "number" && (
                            <span className="text-gray-400">{p.latest_views} views</span>
                          )}
                          {(p.status === "failed" || p.status === "needs_reconnect") && (
                            <span className="text-red-500">{p.error || "Publish failed"}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

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

              {t.previous_video_urls.length > 0 && (
                <div className="mt-1.5">
                  <button
                    onClick={() => setHistoryOpenId(historyOpenId === t.id ? null : t.id)}
                    className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-600"
                  >
                    {historyOpenId === t.id ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                    {t.previous_video_urls.length} previous version{t.previous_video_urls.length > 1 ? "s" : ""}
                  </button>
                  {historyOpenId === t.id && (
                    <div className="flex flex-wrap gap-2 mt-1.5">
                      {[...t.previous_video_urls].reverse().map((url, i) => (
                        <a
                          key={url} href={url} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2 py-1 text-[11px] text-blue-500 hover:underline"
                        >
                          <ExternalLink className="h-3 w-3" /> {i + 1} version{i + 1 > 1 ? "s" : ""} ago
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="mt-2 pt-2 border-t border-gray-50">
                <button
                  onClick={() => setAdvancedOpenId(advancedOpen ? null : t.id)}
                  className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-600"
                >
                  {advancedOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                  Advanced — manual entry
                </button>
                {advancedOpen && (
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-2">
                    <input
                      type="text"
                      defaultValue={t.final_video_url ?? ""}
                      onBlur={(e) => { if (e.target.value !== (t.final_video_url ?? "")) updateToon(t.id, { final_video_url: e.target.value || null }); }}
                      placeholder="Final video URL (override)"
                      className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
                    />
                    <input
                      type="text"
                      defaultValue={t.platform ?? ""}
                      onBlur={(e) => { if (e.target.value !== (t.platform ?? "")) updateToon(t.id, { platform: e.target.value || null }); }}
                      placeholder="Platform, if posted outside Culturix"
                      className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
                    />
                    <select
                      value={t.status}
                      onChange={(e) => updateToon(t.id, { status: e.target.value })}
                      disabled={t.status === "animating"}
                      className="rounded-lg border border-gray-200 px-2 py-1 text-xs disabled:opacity-60"
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s} disabled={MANUALLY_UNSELECTABLE_STATUSES.includes(s)}>{s}</option>
                      ))}
                    </select>
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

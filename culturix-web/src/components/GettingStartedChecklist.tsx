"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Circle, ChevronDown, ChevronUp, ArrowRight } from "lucide-react";
import type { Character, CharacterVariant, ToonScript, Toon, ConnectedAccount } from "@/lib/types";
import type { Tab } from "@/components/CultureToonWorkspace";

interface Props {
  brandId: string;
  onNavigate: (tab: Tab) => void;
}

interface Step {
  label: string;
  hint: string;
  done: boolean;
  tab: Tab;
}

async function _json<T>(url: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return fallback;
    return await res.json();
  } catch {
    return fallback;
  }
}

// The one authoritative "what order do I do things in" guide for a new
// CultureToons brand — pipeline is Character -> (register for video) ->
// Script -> Toon video -> connect an account -> publish. Everything else
// (Relationships, Locations, Episodes) is real but optional, so it's
// listed separately rather than padding out the required path.
//
// Self-fetches its own data rather than taking it as props from
// CultureToonWorkspace — the tab components (ToonManager, ScriptManager,
// etc.) each hold their own local state and don't lift changes up to the
// parent, so props here would go stale the moment the user does anything
// in another tab (e.g. generates a video) without a full brand reload.
// Polling while incomplete mirrors this codebase's existing convention for
// the same reason (ToonManager's mid-generation poll, EpisodeManager's
// mid-stitch poll, CharacterVariantManager's pending-registration poll).
export default function GettingStartedChecklist({ brandId, onNavigate }: Props) {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [variants, setVariants] = useState<CharacterVariant[]>([]);
  const [scripts, setScripts] = useState<ToonScript[]>([]);
  const [toons, setToons] = useState<Toon[]>([]);
  const [connectedAccounts, setConnectedAccounts] = useState<ConnectedAccount[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [collapsed, setCollapsed] = useState<boolean | null>(null); // null = not yet decided

  async function load() {
    const [c, v, s, t, a] = await Promise.all([
      _json<Character[]>(`/api/culturetoons/characters?brand_id=${brandId}&active_only=false`, []),
      _json<CharacterVariant[]>(`/api/culturetoons/variants?brand_id=${brandId}&active_only=false`, []),
      _json<ToonScript[]>(`/api/culturetoons/scripts?brand_id=${brandId}`, []),
      _json<Toon[]>(`/api/culturetoons/toons?brand_id=${brandId}`, []),
      _json<ConnectedAccount[]>(`/api/culturetoons/social/accounts?brand_id=${brandId}`, []),
    ]);
    setCharacters(c); setVariants(v); setScripts(s); setToons(t); setConnectedAccounts(a);
    setLoaded(true);
  }

  useEffect(() => {
    setLoaded(false);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  const steps: Step[] = [
    {
      label: "Create a character", tab: "characters",
      hint: "A name and a generated portrait is enough to start.",
      done: characters.length > 0,
    },
    {
      label: "Register it for video", tab: "characters",
      hint: "One-time Kling registration per variant — required before any video can generate.",
      done: variants.some((v) => v.element_status === "ready"),
    },
    {
      label: "Create a script", tab: "scripts",
      hint: "AI-suggest one from a trend/idea, or write one manually.",
      done: scripts.length > 0,
    },
    {
      label: "Generate a toon's video", tab: "toons",
      hint: "Needs an AI-suggested script (with shots) and a registered character.",
      done: toons.some((t) => !!t.raw_video_url || !!t.final_video_url),
    },
    {
      label: "Connect a social account", tab: "toons",
      hint: "Where finished toons actually publish to.",
      done: connectedAccounts.length > 0,
    },
    {
      label: "Publish your first toon", tab: "toons",
      hint: "One click once you have a finished video and a connected account.",
      done: toons.some((t) => t.status === "posted"),
    },
  ];

  const doneCount = steps.filter((s) => s.done).length;
  const allDone = doneCount === steps.length;
  const firstIncompleteIndex = steps.findIndex((s) => !s.done);

  // Decide the default open/closed state once real data is in (avoids a
  // flash of "expanded" for a brand that's already fully set up) —
  // afterwards it's purely user-controlled.
  useEffect(() => {
    if (collapsed === null && loaded) setCollapsed(allDone);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded]);

  // Keep it fresh while there's still something to do and the user is
  // actually looking at it — same 5s cadence as this codebase's other
  // mid-task polls.
  useEffect(() => {
    if (!loaded || allDone || collapsed) return;
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, allDone, collapsed, brandId]);

  if (collapsed === null) return null; // waiting on the initial load above

  const optional = [
    { label: "Relationships", tab: "relationships" as Tab, hint: "Link two characters (rivalry, siblings, etc.) — feeds script generation." },
    { label: "Locations", tab: "backgrounds" as Tab, hint: "Reusable scene backgrounds to ground videos in a real-feeling place." },
    { label: "Episodes", tab: "episodes" as Tab, hint: "Stitch several toons — or independently-generated scenes — into a longer story." },
  ];

  return (
    <div className="rounded-2xl bg-white border border-gray-100 p-4">
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex items-center justify-between w-full text-left"
      >
        <span className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-900">
            {allDone ? "You're set up" : "Getting started"}
          </span>
          <span className="text-[11px] text-gray-400">{doneCount}/{steps.length}</span>
        </span>
        {collapsed ? <ChevronDown className="h-4 w-4 text-gray-400" /> : <ChevronUp className="h-4 w-4 text-gray-400" />}
      </button>

      {!collapsed && (
        <div className="mt-3 space-y-4">
          <ol className="space-y-1.5">
            {steps.map((step, i) => (
              <li key={step.label}>
                <button
                  onClick={() => onNavigate(step.tab)}
                  className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors ${
                    i === firstIncompleteIndex ? "bg-blue-50 hover:bg-blue-100" : "hover:bg-gray-50"
                  }`}
                >
                  {step.done ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                  ) : (
                    <Circle className={`h-4 w-4 shrink-0 mt-0.5 ${i === firstIncompleteIndex ? "text-blue-400" : "text-gray-300"}`} />
                  )}
                  <span className="flex-1 min-w-0">
                    <span className={`text-xs font-medium ${step.done ? "text-gray-400 line-through" : "text-gray-800"}`}>
                      {step.label}
                    </span>
                    <span className="block text-[11px] text-gray-400">{step.hint}</span>
                  </span>
                  {i === firstIncompleteIndex && <ArrowRight className="h-3.5 w-3.5 text-blue-400 shrink-0 mt-0.5" />}
                </button>
              </li>
            ))}
          </ol>

          <div className="pt-3 border-t border-gray-100">
            <p className="text-[11px] font-medium text-gray-500 mb-1.5">Optional, once you&apos;re comfortable</p>
            <div className="flex flex-wrap gap-1.5">
              {optional.map((o) => (
                <button
                  key={o.label}
                  onClick={() => onNavigate(o.tab)}
                  title={o.hint}
                  className="rounded-full border border-gray-200 text-gray-500 hover:border-blue-300 hover:text-blue-600 text-[11px] px-2.5 py-1 transition-colors"
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

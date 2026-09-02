"use client";

import { useEffect, useState } from "react";
import type { Character, CharacterVariant, ToonScript, Toon, ConnectedAccount } from "@/lib/types";
import type { Tab } from "@/components/CultureToonWorkspace";
import ProductSetupStatus, { type SetupStep, type OptionalSetupStep } from "@/components/onboarding/ProductSetupStatus";

interface Props {
  brandId: string;
  onNavigate: (tab: Tab) => void;
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
//
// Data-fetch/polling/collapsed-state logic lives here; the actual checklist
// rendering is the shared ProductSetupStatus (also used by Shopify).
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

  // Whether this deployment still needs the pre-LTX-2.5 per-character
  // setup. Under 2.5 a portrait is the only prerequisite, so telling users
  // to register with Kling sends them to do work that changes nothing.
  const [legacySetup, setLegacySetup] = useState(true);

  useEffect(() => {
    fetch("/api/culturetoons/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setLegacySetup(!!d.self_hosted_requires_lora))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setLoaded(false);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  const steps: SetupStep<Tab>[] = [
    {
      label: "Create a character", action: "characters",
      hint: "A name and a generated portrait is enough to start.",
      done: characters.length > 0,
    },
    legacySetup
      ? {
          label: "Register it for video", action: "characters" as Tab,
          hint: "One-time Kling registration per variant — required before any video can generate.",
          done: variants.some((v) => v.element_status === "ready"),
        }
      : {
          label: "Give it a portrait", action: "characters" as Tab,
          hint: "That single image carries the character's identity into every video — no registration or training needed.",
          done: variants.some((v) => !!v.image_url),
        },
    {
      label: "Create a script", action: "scripts",
      hint: "AI-suggest one from a trend/idea, or write one manually.",
      done: scripts.length > 0,
    },
    {
      label: "Generate a toon's video", action: "toons",
      hint: "Needs an AI-suggested script (with shots) and a registered character.",
      done: toons.some((t) => !!t.raw_video_url || !!t.final_video_url),
    },
    {
      label: "Connect a social account", action: "toons",
      hint: "Where finished toons actually publish to.",
      done: connectedAccounts.length > 0,
    },
    {
      label: "Publish your first toon", action: "toons",
      hint: "One click once you have a finished video and a connected account.",
      done: toons.some((t) => t.status === "posted"),
    },
  ];

  const allDone = steps.every((s) => s.done);

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

  const optional: OptionalSetupStep<Tab>[] = [
    { label: "Relationships", action: "relationships", hint: "Link two characters (rivalry, siblings, etc.) — feeds script generation." },
    { label: "Locations", action: "backgrounds", hint: "Reusable scene backgrounds to ground videos in a real-feeling place." },
    { label: "Episodes", action: "episodes", hint: "Stitch several toons — or independently-generated scenes — into a longer story." },
  ];

  return (
    <ProductSetupStatus
      title="Getting started"
      steps={steps}
      optionalSteps={optional}
      collapsed={collapsed}
      onToggleCollapsed={() => setCollapsed((c) => !c)}
      onNavigate={onNavigate}
    />
  );
}

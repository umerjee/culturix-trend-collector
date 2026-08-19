"use client";

import { useState } from "react";
import { Users, Heart, Image as ImageIcon, FileText, Clapperboard, Film, Wallet } from "lucide-react";
import type { CharacterBrand, Character, CharacterVariant, ToonBackground, ToonScript, Toon, ToonEpisode } from "@/lib/types";
import CharacterVariantManager from "@/components/CharacterVariantManager";
import RelationshipManager from "@/components/RelationshipManager";
import BackgroundGallery from "@/components/BackgroundGallery";
import ScriptManager from "@/components/ScriptManager";
import ToonManager from "@/components/ToonManager";
import EpisodeManager from "@/components/EpisodeManager";
import UsageBudgetPanel from "@/components/UsageBudgetPanel";
import GettingStartedChecklist from "@/components/GettingStartedChecklist";

interface Props {
  brand: CharacterBrand;
  initialCharacters: Character[];
  initialVariants: CharacterVariant[];
  initialBackgrounds: ToonBackground[];
  initialScripts: ToonScript[];
  initialToons: Toon[];
  initialEpisodes: ToonEpisode[];
  onBrandUpdated: (brand: CharacterBrand) => void;
}

export type Tab = "characters" | "relationships" | "backgrounds" | "scripts" | "toons" | "episodes" | "usage";

type TabDef = { key: Tab; label: string; icon: React.ReactNode };

// Grouped so the 7-tab bar reads as "core production flow" vs. "supporting
// setup" instead of one flat undifferentiated row — purely visual, the
// underlying tab-switching state and every manager component is untouched.
const PRIMARY_TABS: TabDef[] = [
  { key: "characters", label: "Characters", icon: <Users className="h-3.5 w-3.5" /> },
  { key: "scripts", label: "Scripts", icon: <FileText className="h-3.5 w-3.5" /> },
  { key: "toons", label: "Toons", icon: <Clapperboard className="h-3.5 w-3.5" /> },
  { key: "episodes", label: "Episodes", icon: <Film className="h-3.5 w-3.5" /> },
];

const ADVANCED_TABS: TabDef[] = [
  { key: "relationships", label: "Relationships", icon: <Heart className="h-3.5 w-3.5" /> },
  { key: "backgrounds", label: "Locations", icon: <ImageIcon className="h-3.5 w-3.5" /> },
  { key: "usage", label: "Usage & Budget", icon: <Wallet className="h-3.5 w-3.5" /> },
];

export default function CultureToonWorkspace({
  brand, initialCharacters, initialVariants, initialBackgrounds, initialScripts, initialToons, initialEpisodes,
  onBrandUpdated,
}: Props) {
  const [tab, setTab] = useState<Tab>("characters");
  // Lifted up from whichever tab used to "own" each list (Characters owned
  // variants, Locations owned backgrounds, Scripts owned scripts, Toons
  // owned toons) so every tab reads the same live data instead of the
  // one-time initial* snapshot from page load. Confirmed live: archiving a
  // character in the Characters tab left it still showing in the Scripts
  // tab's cast picker until a full page reload, since that tab held its own
  // frozen copy from mount.
  //
  // `characters` is lifted for a DIFFERENT reason than the rest: each tab
  // below is conditionally rendered ({tab === "x" && <Component/>}), which
  // fully unmounts the component when you switch away and remounts a fresh
  // instance when you switch back — any state owned inside that component
  // resets to whatever prop it was seeded with, discarding anything changed
  // in between. Confirmed live: a user AI-generated character portraits,
  // switched to the Toons tab to create a toon, and the portraits were gone
  // on returning to Characters — CharacterVariantManager's own `characters`
  // state had reset to the original page-load snapshot. Lifting it here
  // (a component that's never unmounted by tab switching) fixes that.
  const [characters, setCharacters] = useState(initialCharacters);
  const [variants, setVariants] = useState(initialVariants);
  const [backgrounds, setBackgrounds] = useState(initialBackgrounds);
  const [scripts, setScripts] = useState(initialScripts);
  // Excludes archived up front (status flips to "archived" server-side on
  // delete, row isn't removed) — matches ToonManager's original filter, now
  // applied once here so an archived toon can't reappear in Episodes'
  // "attach" picker either.
  const [toons, setToons] = useState(initialToons.filter((t) => t.status !== "archived"));
  // Set when a blocker elsewhere (e.g. ToonManager's "this character isn't
  // registered yet" warning) wants to land the user directly on the
  // specific character/variant that needs attention, instead of just
  // naming the Characters tab and leaving them to find it themselves.
  const [focusVariantId, setFocusVariantId] = useState<string | null>(null);

  function jumpToVariant(variantId: string) {
    setFocusVariantId(variantId);
    setTab("characters");
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-gray-900">{brand.name}</h2>
          {brand.description && <p className="text-xs text-gray-400 mt-0.5">{brand.description}</p>}
        </div>
      </div>

      <GettingStartedChecklist brandId={brand.id} onNavigate={setTab} />

      <div className="flex items-center gap-1 border-b border-gray-100 overflow-x-auto">
        {PRIMARY_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`inline-flex items-center gap-1.5 text-sm font-medium px-3 py-2 border-b-2 shrink-0 transition-colors ${
              tab === t.key ? "border-primary-600 text-primary-600" : "border-transparent text-gray-500 hover:text-gray-800"
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
        <span className="mx-1.5 h-5 w-px bg-gray-200 shrink-0" />
        <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide shrink-0 pr-1">Advanced</span>
        {ADVANCED_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`inline-flex items-center gap-1.5 text-sm font-medium px-3 py-2 border-b-2 shrink-0 transition-colors ${
              tab === t.key ? "border-primary-600 text-primary-600" : "border-transparent text-gray-500 hover:text-gray-800"
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {tab === "characters" && (
        <CharacterVariantManager
          brandId={brand.id}
          hasElevenLabsKey={brand.has_elevenlabs_key}
          characters={characters}
          setCharacters={setCharacters}
          variants={variants}
          setVariants={setVariants}
          focusVariantId={focusVariantId}
        />
      )}
      {tab === "relationships" && <RelationshipManager brandId={brand.id} />}
      {tab === "backgrounds" && <BackgroundGallery brandId={brand.id} backgrounds={backgrounds} setBackgrounds={setBackgrounds} />}
      {tab === "scripts" && (
        <ScriptManager
          brandId={brand.id}
          scripts={scripts}
          setScripts={setScripts}
          variants={variants}
          backgrounds={backgrounds}
          setBackgrounds={setBackgrounds}
          initialTrendInterests={brand.trend_interests}
        />
      )}
      {tab === "toons" && (
        <ToonManager
          brandId={brand.id}
          brandName={brand.name}
          toons={toons}
          setToons={setToons}
          scripts={scripts}
          variants={variants}
          backgrounds={backgrounds}
          onJumpToVariant={jumpToVariant}
        />
      )}
      {tab === "episodes" && (
        <EpisodeManager
          brandId={brand.id}
          initialEpisodes={initialEpisodes}
          toons={toons}
          setToons={setToons}
          variants={variants}
          scripts={scripts}
          backgrounds={backgrounds}
        />
      )}
      {tab === "usage" && <UsageBudgetPanel brand={brand} onBrandUpdated={onBrandUpdated} />}
    </div>
  );
}

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

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: "characters", label: "Characters", icon: <Users className="h-3.5 w-3.5" /> },
  { key: "relationships", label: "Relationships", icon: <Heart className="h-3.5 w-3.5" /> },
  { key: "backgrounds", label: "Locations", icon: <ImageIcon className="h-3.5 w-3.5" /> },
  { key: "scripts", label: "Scripts", icon: <FileText className="h-3.5 w-3.5" /> },
  { key: "toons", label: "Toons", icon: <Clapperboard className="h-3.5 w-3.5" /> },
  { key: "episodes", label: "Episodes", icon: <Film className="h-3.5 w-3.5" /> },
  { key: "usage", label: "Usage & Budget", icon: <Wallet className="h-3.5 w-3.5" /> },
];

export default function CultureToonWorkspace({
  brand, initialCharacters, initialVariants, initialBackgrounds, initialScripts, initialToons, initialEpisodes,
  onBrandUpdated,
}: Props) {
  const [tab, setTab] = useState<Tab>("characters");
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

      <div className="flex items-center gap-1 border-b border-gray-100">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`inline-flex items-center gap-1.5 text-sm font-medium px-3 py-2 border-b-2 transition-colors ${
              tab === t.key ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-800"
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
          initialCharacters={initialCharacters}
          initialVariants={initialVariants}
          focusVariantId={focusVariantId}
        />
      )}
      {tab === "relationships" && <RelationshipManager brandId={brand.id} />}
      {tab === "backgrounds" && <BackgroundGallery brandId={brand.id} initialBackgrounds={initialBackgrounds} />}
      {tab === "scripts" && (
        <ScriptManager
          brandId={brand.id}
          initialScripts={initialScripts}
          variants={initialVariants}
          backgrounds={initialBackgrounds}
          initialTrendInterests={brand.trend_interests}
        />
      )}
      {tab === "toons" && (
        <ToonManager
          brandId={brand.id}
          brandName={brand.name}
          initialToons={initialToons}
          scripts={initialScripts}
          variants={initialVariants}
          backgrounds={initialBackgrounds}
          onJumpToVariant={jumpToVariant}
        />
      )}
      {tab === "episodes" && (
        <EpisodeManager
          brandId={brand.id}
          initialEpisodes={initialEpisodes}
          initialToons={initialToons}
          variants={initialVariants}
          scripts={initialScripts}
          backgrounds={initialBackgrounds}
        />
      )}
      {tab === "usage" && <UsageBudgetPanel brand={brand} onBrandUpdated={onBrandUpdated} />}
    </div>
  );
}

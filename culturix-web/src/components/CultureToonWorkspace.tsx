"use client";

import { useState } from "react";
import { Users, Image as ImageIcon, FileText, Clapperboard } from "lucide-react";
import type { CharacterBrand, Character, CharacterVariant, ToonBackground, ToonScript, Toon } from "@/lib/types";
import CharacterVariantManager from "@/components/CharacterVariantManager";
import BackgroundGallery from "@/components/BackgroundGallery";
import ScriptManager from "@/components/ScriptManager";
import ToonManager from "@/components/ToonManager";

interface Props {
  brand: CharacterBrand;
  initialCharacters: Character[];
  initialVariants: CharacterVariant[];
  initialBackgrounds: ToonBackground[];
  initialScripts: ToonScript[];
  initialToons: Toon[];
}

type Tab = "characters" | "backgrounds" | "scripts" | "toons";

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: "characters", label: "Characters", icon: <Users className="h-3.5 w-3.5" /> },
  { key: "backgrounds", label: "Backgrounds", icon: <ImageIcon className="h-3.5 w-3.5" /> },
  { key: "scripts", label: "Scripts", icon: <FileText className="h-3.5 w-3.5" /> },
  { key: "toons", label: "Toons", icon: <Clapperboard className="h-3.5 w-3.5" /> },
];

export default function CultureToonWorkspace({
  brand, initialCharacters, initialVariants, initialBackgrounds, initialScripts, initialToons,
}: Props) {
  const [tab, setTab] = useState<Tab>("characters");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-gray-900">{brand.name}</h2>
          {brand.description && <p className="text-xs text-gray-400 mt-0.5">{brand.description}</p>}
        </div>
      </div>

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
        />
      )}
      {tab === "backgrounds" && <BackgroundGallery brandId={brand.id} initialBackgrounds={initialBackgrounds} />}
      {tab === "scripts" && (
        <ScriptManager brandId={brand.id} initialScripts={initialScripts} variants={initialVariants} />
      )}
      {tab === "toons" && (
        <ToonManager
          brandId={brand.id}
          initialToons={initialToons}
          scripts={initialScripts}
          variants={initialVariants}
          backgrounds={initialBackgrounds}
        />
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2 } from "lucide-react";
import type { CharacterBrand, Character, CharacterVariant, ToonBackground, ToonScript, Toon } from "@/lib/types";
import CultureToonBrandForm from "@/components/CultureToonBrandForm";
import CultureToonWorkspace from "@/components/CultureToonWorkspace";

interface Props {
  initialBrands: CharacterBrand[];
}

interface BrandData {
  characters: Character[];
  variants: CharacterVariant[];
  backgrounds: ToonBackground[];
  scripts: ToonScript[];
  toons: Toon[];
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

export default function CultureToonApp({ initialBrands }: Props) {
  const [brands, setBrands] = useState(initialBrands);
  const [selectedBrandId, setSelectedBrandId] = useState<string | null>(initialBrands[0]?.id ?? null);
  const [data, setData] = useState<BrandData | null>(null);
  const [loading, setLoading] = useState(false);
  const [showNewBrandForm, setShowNewBrandForm] = useState(false);

  useEffect(() => {
    if (!selectedBrandId) return;
    let cancelled = false;
    setLoading(true);
    setData(null);
    Promise.all([
      _json<Character[]>(`/api/culturetoons/characters?brand_id=${selectedBrandId}&active_only=false`, []),
      _json<CharacterVariant[]>(`/api/culturetoons/variants?brand_id=${selectedBrandId}&active_only=false`, []),
      _json<ToonBackground[]>(`/api/culturetoons/backgrounds?brand_id=${selectedBrandId}&active_only=false`, []),
      _json<ToonScript[]>(`/api/culturetoons/scripts?brand_id=${selectedBrandId}`, []),
      _json<Toon[]>(`/api/culturetoons/toons?brand_id=${selectedBrandId}`, []),
    ]).then(([characters, variants, backgrounds, scripts, toons]) => {
      if (cancelled) return;
      setData({ characters, variants, backgrounds, scripts, toons });
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [selectedBrandId]);

  if (brands.length === 0 || showNewBrandForm) {
    return (
      <div>
        {brands.length > 0 && (
          <button onClick={() => setShowNewBrandForm(false)} className="text-sm text-gray-500 hover:text-gray-700 mb-3">
            ← Back to your brands
          </button>
        )}
        <CultureToonBrandForm
          onCreated={(brand) => {
            setBrands((prev) => [...prev, brand]);
            setSelectedBrandId(brand.id);
            setShowNewBrandForm(false);
          }}
        />
      </div>
    );
  }

  const selectedBrand = brands.find((b) => b.id === selectedBrandId) ?? brands[0];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 flex-wrap">
        {brands.map((b) => (
          <button
            key={b.id}
            onClick={() => setSelectedBrandId(b.id)}
            className={`text-sm font-medium rounded-lg px-3 py-1.5 transition-colors ${
              b.id === selectedBrand.id
                ? "bg-blue-600 text-white"
                : "bg-white border border-gray-200 text-gray-600 hover:border-blue-300"
            }`}
          >
            {b.name}
          </button>
        ))}
        <button
          onClick={() => setShowNewBrandForm(true)}
          className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-blue-600 rounded-lg px-3 py-1.5 border border-dashed border-gray-200 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" /> New brand
        </button>
      </div>

      {loading || !data ? (
        <div className="flex items-center gap-2 text-sm text-gray-400 py-16 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading {selectedBrand.name}…
        </div>
      ) : (
        <CultureToonWorkspace
          key={selectedBrand.id}
          brand={selectedBrand}
          initialCharacters={data.characters}
          initialVariants={data.variants}
          initialBackgrounds={data.backgrounds}
          initialScripts={data.scripts}
          initialToons={data.toons}
        />
      )}
    </div>
  );
}

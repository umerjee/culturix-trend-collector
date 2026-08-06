"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, ArrowRight } from "lucide-react";
import type { CharacterBrand, Character, CharacterVariant, ToonBackground, ToonScript, Toon, ToonEpisode } from "@/lib/types";
import CultureToonBrandForm from "@/components/CultureToonBrandForm";
import CultureToonWorkspace from "@/components/CultureToonWorkspace";
import ConnectedAccountsPanel from "@/components/ConnectedAccountsPanel";

interface Props {
  initialBrands: CharacterBrand[];
}

interface BrandData {
  characters: Character[];
  variants: CharacterVariant[];
  backgrounds: ToonBackground[];
  scripts: ToonScript[];
  toons: Toon[];
  episodes: ToonEpisode[];
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
  // A freshly-created brand with at least one target platform picked lands
  // here instead of straight into the workspace — one guided pass through
  // roster + platforms + connections, per harmonic-mixing-flame.md's Phase 4.
  const [pendingConnectBrand, setPendingConnectBrand] = useState<CharacterBrand | null>(null);

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
      _json<ToonEpisode[]>(`/api/culturetoons/episodes?brand_id=${selectedBrandId}`, []),
    ]).then(([characters, variants, backgrounds, scripts, toons, episodes]) => {
      if (cancelled) return;
      setData({ characters, variants, backgrounds, scripts, toons, episodes });
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
            setShowNewBrandForm(false);
            if (brand.target_platforms && brand.target_platforms.length > 0) {
              setPendingConnectBrand(brand);
            } else {
              setSelectedBrandId(brand.id);
            }
          }}
        />
      </div>
    );
  }

  if (pendingConnectBrand) {
    return (
      <div className="rounded-2xl border border-gray-100 bg-white p-6 max-w-lg mx-auto">
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Almost done — connect &ldquo;{pendingConnectBrand.name}&rdquo;&apos;s accounts</h3>
        <p className="text-xs text-gray-400 mb-4">
          Connect the accounts you picked so finished toons can publish directly. Optional — you
          can always do this later from the Toons tab.
        </p>
        <ConnectedAccountsPanel
          brandId={pendingConnectBrand.id}
          brandName={pendingConnectBrand.name}
          platforms={pendingConnectBrand.target_platforms}
        />
        <button
          onClick={() => { setSelectedBrandId(pendingConnectBrand.id); setPendingConnectBrand(null); }}
          className="mt-5 w-full inline-flex items-center justify-center gap-1.5 rounded-xl bg-blue-600 text-white font-semibold py-3 hover:bg-blue-700 transition"
        >
          Continue to {pendingConnectBrand.name} <ArrowRight className="h-4 w-4" />
        </button>
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
          initialEpisodes={data.episodes}
        />
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Loader2, ArrowRight } from "lucide-react";
import type { CharacterBrand, Character, CharacterVariant, ToonBackground, ToonScript, Toon, ToonEpisode } from "@/lib/types";
import CultureToonBrandForm from "@/components/CultureToonBrandForm";
import CultureToonWorkspace, { type Tab } from "@/components/CultureToonWorkspace";
import ConnectedAccountsPanel from "@/components/ConnectedAccountsPanel";

interface Props {
  initialBrands: CharacterBrand[];
  initialTab?: Tab;
  showWorldLibrary?: boolean;
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

export default function CultureToonApp({ initialBrands, initialTab = "characters", showWorldLibrary = false }: Props) {
  // World is a system-owned persistence brand for subject-first Features, not
  // a user-owned character account. Keep it out of this character workflow.
  const toonBrands = initialBrands.filter((brand) => brand.name.toLowerCase() !== "world");
  const [brands, setBrands] = useState(toonBrands);
  const [selectedBrandId, setSelectedBrandId] = useState<string | null>(toonBrands[0]?.id ?? null);
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
    if (brands.length === 0 && !showNewBrandForm) {
      return (
        <div className="rounded-3xl border border-dashed border-gray-200 bg-gradient-to-br from-white via-gray-50 to-primary-50/30 p-6 sm:p-8">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary-600">Comedy studio</p>
            <h2 className="mt-3 text-2xl font-semibold text-gray-900">Create your first toon brand</h2>
            <p className="mt-2 text-sm text-gray-600">
              Start with a brand and a target platform, then move into characters, scripts, and final video production in a single flow.
            </p>
          </div>

          <div className="mt-6 flex flex-wrap gap-3">
            <button
              onClick={() => setShowNewBrandForm(true)}
              className="inline-flex items-center justify-center rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700"
            >
              Create brand
            </button>
            {showWorldLibrary && (
              <Link
                href="/admin/curated-items"
                className="inline-flex items-center justify-center rounded-xl border border-purple-200 bg-purple-50 px-4 py-2.5 text-sm font-semibold text-purple-700 transition hover:border-purple-300 hover:bg-purple-100"
              >
                Open world source library
              </Link>
            )}
          </div>

          <div className="mt-8 grid gap-3 md:grid-cols-3">
            {[
              "Define the brand and target platform",
              "Create characters, variants, and scripts",
              "Generate and publish the final toon",
            ].map((step, index) => (
              <div key={step} className="rounded-2xl border border-gray-200 bg-white p-4">
                <div className="mb-3 inline-flex h-7 w-7 items-center justify-center rounded-full bg-gray-100 text-xs font-semibold text-gray-600">
                  {index + 1}
                </div>
                <p className="text-sm text-gray-700">{step}</p>
              </div>
            ))}
          </div>
        </div>
      );
    }

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
          className="mt-5 w-full inline-flex items-center justify-center gap-1.5 rounded-xl bg-primary-600 text-white font-semibold py-3 hover:bg-primary-700 transition"
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
                ? "bg-primary-600 text-white"
                : "bg-white border border-gray-200 text-gray-600 hover:border-primary-300"
            }`}
          >
            {b.name}
          </button>
        ))}
        <button
          onClick={() => setShowNewBrandForm(true)}
          className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-primary-600 rounded-lg px-3 py-1.5 border border-dashed border-gray-200 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" /> New brand
        </button>
        {showWorldLibrary && (
          <Link href="/admin/curated-items" className="inline-flex items-center gap-1 text-sm font-medium text-purple-600 hover:text-purple-800 rounded-lg px-3 py-1.5 border border-purple-200 bg-purple-50 transition-colors">
            World source library
          </Link>
        )}
      </div>

      {loading || !data ? (
        <div className="flex items-center gap-2 text-sm text-gray-400 py-16 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading {selectedBrand.name}…
        </div>
      ) : (
        <CultureToonWorkspace
          key={selectedBrand.id}
          brand={selectedBrand}
          initialTab={initialTab}
          initialCharacters={data.characters}
          initialVariants={data.variants}
          initialBackgrounds={data.backgrounds}
          initialScripts={data.scripts}
          initialToons={data.toons}
          initialEpisodes={data.episodes}
          onBrandUpdated={(updated) => setBrands((prev) => prev.map((b) => (b.id === updated.id ? updated : b)))}
        />
      )}
    </div>
  );
}

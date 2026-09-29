"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Search, X, Loader2 } from "lucide-react";
import countries from "i18n-iso-countries";
import WorldMap from "@/components/world/WorldMap";
import CategoryGrid from "@/components/world/CategoryGrid";
import FeatureCard from "@/components/world/FeatureCard";
import { CATEGORY_LABELS } from "@/lib/worldTypes";
import type { WorldFeature } from "@/lib/worldTypes";

const SEARCH_DEBOUNCE_MS = 350;

// Ties the map, category tiles, search box and result grid into one interactive surface instead
// of three disconnected pieces (map click -> separate region page; category tile -> full page
// reload; search -> form submit reload). Selecting a country or category filters the SAME grid
// in place, with a removable filter-chip bar so it's always clear what's active. page.tsx still
// does the initial server-side fetch (so the first paint and SEO aren't client-fetch-dependent)
// and hands it here as `initialFeatures`; every filter change after that re-fetches client-side.
export default function WorldExplorer({
  initialFeatures, initialCategory, initialRegion, initialQuery,
}: {
  initialFeatures: WorldFeature[]; initialCategory?: string; initialRegion?: string; initialQuery?: string;
}) {
  const router = useRouter();
  const [selectedRegion, setSelectedRegion] = useState<string | null>(initialRegion || null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(initialCategory || null);
  const [search, setSearch] = useState(initialQuery || "");
  const [debouncedSearch, setDebouncedSearch] = useState(initialQuery || "");
  const [features, setFeatures] = useState<WorldFeature[]>(initialFeatures);
  const [loading, setLoading] = useState(false);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    // Skip the very first run: page.tsx already fetched this exact combination server-side, so
    // refetching immediately on mount would just be a redundant network round-trip.
    if (!hasLoadedOnce) { setHasLoadedOnce(true); return; }
    setLoading(true);
    const params = new URLSearchParams({ limit: "24" });
    if (selectedRegion) params.set("region", selectedRegion);
    if (selectedCategory) params.set("category", selectedCategory);
    if (debouncedSearch) params.set("q", debouncedSearch);
    fetch(`/api/world/features?${params.toString()}`)
      .then((r) => (r.ok ? r.json() : { features: [] }))
      .then((data) => setFeatures(Array.isArray(data.features) ? data.features : []))
      .catch(() => setFeatures([]))
      .finally(() => setLoading(false));

    // Keep the URL in sync (shareable/bookmarkable, survives refresh) without a server round-trip
    // — shallow client navigation only, the state above already drives what's on screen.
    const urlParams = new URLSearchParams();
    if (selectedRegion) urlParams.set("region", selectedRegion);
    if (selectedCategory) urlParams.set("category", selectedCategory);
    if (debouncedSearch) urlParams.set("q", debouncedSearch);
    const qs = urlParams.toString();
    router.replace(qs ? `/world?${qs}` : "/world", { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- router/hasLoadedOnce deliberately excluded, see effect body
  }, [selectedRegion, selectedCategory, debouncedSearch]);

  const regionName = useMemo(
    () => (selectedRegion ? countries.getName(selectedRegion, "en") || selectedRegion : null),
    [selectedRegion],
  );

  const clearAll = useCallback(() => {
    setSelectedRegion(null);
    setSelectedCategory(null);
    setSearch("");
  }, []);

  const hasActiveFilters = Boolean(selectedRegion || selectedCategory || search);

  return (
    <>
      <section className="mb-10">
        <WorldMap onSelectRegion={setSelectedRegion} selectedRegion={selectedRegion} />
      </section>

      <section id="categories" className="mb-6 scroll-mt-20">
        <CategoryGrid active={selectedCategory} onSelect={setSelectedCategory} />
      </section>

      <div className="mb-6 max-w-md mx-auto">
        <div className="relative">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search places, phenomena, species..."
            className="w-full rounded-xl border border-gray-200 pl-10 pr-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-300"
          />
        </div>
      </div>

      {hasActiveFilters && (
        <div className="mb-6 flex flex-wrap items-center justify-center gap-2 text-sm">
          <span className="text-gray-400">Showing:</span>
          {regionName && (
            <button onClick={() => setSelectedRegion(null)} className="inline-flex items-center gap-1 rounded-full bg-purple-50 text-purple-700 pl-3 pr-2 py-1 font-medium hover:bg-purple-100">
              {regionName} <X className="h-3 w-3" />
            </button>
          )}
          {selectedCategory && (
            <button onClick={() => setSelectedCategory(null)} className="inline-flex items-center gap-1 rounded-full bg-purple-50 text-purple-700 pl-3 pr-2 py-1 font-medium hover:bg-purple-100">
              {CATEGORY_LABELS[selectedCategory] || selectedCategory} <X className="h-3 w-3" />
            </button>
          )}
          {search && (
            <button onClick={() => setSearch("")} className="inline-flex items-center gap-1 rounded-full bg-purple-50 text-purple-700 pl-3 pr-2 py-1 font-medium hover:bg-purple-100">
              &quot;{search}&quot; <X className="h-3 w-3" />
            </button>
          )}
          <button onClick={clearAll} className="text-xs text-gray-400 hover:text-gray-600 underline ml-1">
            Clear all
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-gray-400">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading...
        </div>
      ) : features.length === 0 ? (
        <p className="text-center text-sm text-gray-400 py-10">
          {hasActiveFilters ? "No Features match these filters yet." : "No World Features published yet — check back soon."}
        </p>
      ) : (
        <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
          {features.map((f) => (
            <FeatureCard key={f.id} feature={f} />
          ))}
        </section>
      )}
    </>
  );
}

"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import dynamic from "next/dynamic";
import { Search, X, ChevronDown, Map as MapIcon, RefreshCw, Compass } from "lucide-react";
import FeatureCard from "@/components/world/FeatureCard";
import FeatureCardSkeleton from "@/components/world/FeatureCardSkeleton";
import { CATEGORY_LABELS, WORLD_FEED_PAGE_SIZE } from "@/lib/worldTypes";
import type { WorldFeature } from "@/lib/worldTypes";
import { CATEGORY_ICONS, CATEGORY_COLORS } from "@/lib/worldCategoryVisuals";
import { countryName, flagEmoji } from "@/lib/worldPlaces";
import { useLocale } from "@/components/i18n/LocaleProvider";

// The map (d3-geo, topojson, world atlas) is most of this page's JS; it only loads once the
// "Explore by place" panel is opened, which on phones may be never.
const WorldMap = dynamic(() => import("@/components/world/WorldMap"), {
  ssr: false,
  loading: () => (
    <div aria-hidden="true" className="rounded-2xl bg-gradient-to-b from-sky-100 via-sky-50 to-white animate-pulse motion-reduce:animate-none" style={{ aspectRatio: "800 / 500", maxHeight: 480 }} />
  ),
});

const SEARCH_DEBOUNCE_MS = 350;
const CATEGORY_KEYS = Object.keys(CATEGORY_LABELS);
// Matches the breakpoint where the map panel starts open: phones and iPad portrait (768) get the
// feed first with the map one tap away; desktop and iPad landscape (1024+) have room for both.
const MAP_OPEN_QUERY = "(min-width: 1024px)";

type Status = "idle" | "loading" | "loading-more" | "error" | "error-more";

function dedupe(list: WorldFeature[]): WorldFeature[] {
  const seen = new Set<string>();
  return list.filter((f) => (seen.has(f.id) ? false : (seen.add(f.id), true)));
}

// The /world feed. Category chips, the place picker, search and the (collapsible) map all drive
// ONE feed in place, kept in sync with the URL. page.tsx does the first page server-side (first
// paint and SEO don't depend on client JS); every later page and every filter change is fetched
// here, `WORLD_FEED_PAGE_SIZE` at a time, as the sentinel under the grid scrolls into view.
export default function WorldExplorer({
  initialFeatures, initialTotal, initialError, initialCategory, initialRegion, initialQuery,
}: {
  initialFeatures: WorldFeature[]; initialTotal: number; initialError?: boolean;
  initialCategory?: string; initialRegion?: string; initialQuery?: string;
}) {
  const { locale, messages } = useLocale();
  const t = messages.world;

  const [selectedRegion, setSelectedRegion] = useState<string | null>(initialRegion?.toUpperCase() || null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(initialCategory || null);
  const [search, setSearch] = useState(initialQuery || "");
  const [debouncedSearch, setDebouncedSearch] = useState(initialQuery || "");
  const [features, setFeatures] = useState<WorldFeature[]>(initialFeatures);
  const [total, setTotal] = useState(initialTotal);
  const [status, setStatus] = useState<Status>(initialError ? "error" : "idle");
  const [mapOpen, setMapOpen] = useState(false);
  const [places, setPlaces] = useState<string[]>([]);

  const featuresRef = useRef(features);
  featuresRef.current = features;
  const requestIdRef = useRef(0);
  const inFlightRef = useRef(false);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const isFirstFilterRun = useRef(true);

  useEffect(() => {
    if (window.matchMedia(MAP_OPEN_QUERY).matches) setMapOpen(true);
    // Filters live in the URL via history.replaceState, which the router doesn't know about: on
    // Back from a video it restores the server payload for the URL the page was first opened
    // with (e.g. plain /world) while the address bar shows the filtered one. The address bar
    // is the truth; adopt it if it disagrees with the props.
    const url = new URLSearchParams(window.location.search);
    const region = url.get("region")?.toUpperCase() || null;
    const category = url.get("category") || null;
    const q = url.get("q") || "";
    if (region !== selectedRegion) setSelectedRegion(region);
    if (category !== selectedCategory) setSelectedCategory(category);
    if (q !== search) { setSearch(q); setDebouncedSearch(q); }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only reconciliation
  }, []);

  useEffect(() => {
    fetch("/api/world/regions")
      .then((r) => (r.ok ? r.json() : { regions: [] }))
      .then((data: { regions?: { region: string; feature_count: number }[] }) =>
        setPlaces((data.regions || []).filter((r) => r.feature_count > 0).map((r) => r.region)),
      )
      .catch(() => setPlaces([]));
  }, []);

  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [search]);

  const filterQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (selectedRegion) params.set("region", selectedRegion);
    if (selectedCategory) params.set("category", selectedCategory);
    if (debouncedSearch) params.set("q", debouncedSearch);
    return params;
  }, [selectedRegion, selectedCategory, debouncedSearch]);

  // `reset` starts the feed over for new filters; otherwise appends the next page. A request
  // counter (not just the in-flight flag) drops responses for filters that have since changed,
  // so a slow page for old filters can never land on top of a newer result.
  const loadPage = useCallback(async (reset: boolean) => {
    if (!reset && inFlightRef.current) return;
    const requestId = ++requestIdRef.current;
    inFlightRef.current = true;
    const offset = reset ? 0 : featuresRef.current.length;
    setStatus(reset ? "loading" : "loading-more");
    const params = new URLSearchParams(filterQuery);
    params.set("limit", String(WORLD_FEED_PAGE_SIZE));
    params.set("offset", String(offset));
    try {
      const res = await fetch(`/api/world/features?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (requestId !== requestIdRef.current) return;
      const page: WorldFeature[] = Array.isArray(data.features) ? data.features : [];
      setFeatures((prev) => (reset ? page : dedupe([...prev, ...page])));
      setTotal(typeof data.total === "number" ? data.total : offset + page.length);
      setStatus("idle");
    } catch {
      if (requestId !== requestIdRef.current) return;
      setStatus(reset ? "error" : "error-more");
    } finally {
      if (requestId === requestIdRef.current) inFlightRef.current = false;
    }
  }, [filterQuery]);

  useEffect(() => {
    // page.tsx already fetched the initial filter combination server-side.
    if (isFirstFilterRun.current) { isFirstFilterRun.current = false; return; }
    loadPage(true);

    // URL sync (shareable, survives refresh). history.replaceState rather than router.replace:
    // router.replace re-renders page.tsx on the server, a second backend fetch per filter change
    // that this component then ignores. `lang` belongs to the language switcher; carried over.
    const urlParams = new URLSearchParams(filterQuery);
    const lang = new URLSearchParams(window.location.search).get("lang");
    if (lang) urlParams.set("lang", lang);
    const qs = urlParams.toString();
    window.history.replaceState(window.history.state, "", qs ? `/world?${qs}` : "/world");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadPage changes exactly when filterQuery does
  }, [filterQuery]);

  const hasMore = features.length < total;

  // Re-created whenever the feed grows or settles, so a sentinel that is STILL visible after a
  // page lands (tall screen, short page) immediately triggers the next one instead of waiting
  // for a scroll that may never come.
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || status !== "idle" || !hasMore) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadPage(false); },
      { rootMargin: "600px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [status, hasMore, features.length, loadPage]);

  const clearAll = useCallback(() => {
    setSelectedRegion(null);
    setSelectedCategory(null);
    setSearch("");
  }, []);

  const placeOptions = useMemo(() => {
    const codes = new Set(places);
    if (selectedRegion) codes.add(selectedRegion);
    return Array.from(codes)
      .map((code) => ({ code, name: countryName(code, locale) || code }))
      .sort((a, b) => a.name.localeCompare(b.name, locale));
  }, [places, selectedRegion, locale]);

  const hasActiveFilters = Boolean(selectedRegion || selectedCategory || debouncedSearch);
  const regionName = countryName(selectedRegion, locale);
  const categoryLabel = (key: string) => t.categories[key] || CATEGORY_LABELS[key] || key;
  const suggestions = CATEGORY_KEYS.filter((k) => k !== selectedCategory && k !== "custom").slice(0, 2);

  const chipClass = (active: boolean) =>
    `inline-flex shrink-0 items-center gap-1.5 min-h-[44px] rounded-full border px-4 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 ${
      active ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 bg-white text-gray-700 hover:border-purple-300 hover:text-purple-700"
    }`;

  return (
    <>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pt-6 pb-3">
        <h1 className="text-xl sm:text-2xl font-bold text-gray-900">{t.title}</h1>
        <p className="text-sm text-gray-500">{t.tagline}</p>
      </div>

      <div
        id="categories"
        className="sticky top-16 z-20 -mx-4 sm:-mx-6 px-4 sm:px-6 py-2 bg-white/95 backdrop-blur-sm border-b border-gray-100 scroll-mt-16"
      >
        <div className="flex flex-col gap-2">
          <div
            role="group"
            aria-label={t.filtersLabel}
            className="flex gap-2 overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0 pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            <button type="button" aria-pressed={!selectedCategory} onClick={() => setSelectedCategory(null)} className={chipClass(!selectedCategory)}>
              {t.all}
            </button>
            {CATEGORY_KEYS.map((key) => {
              const Icon = CATEGORY_ICONS[key];
              const active = selectedCategory === key;
              return (
                <button
                  key={key}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setSelectedCategory(active ? null : key)}
                  className={chipClass(active)}
                >
                  <Icon className="h-4 w-4" style={{ color: active ? "#fff" : CATEGORY_COLORS[key] }} aria-hidden="true" />
                  {categoryLabel(key)}
                </button>
              );
            })}
          </div>

          <div className="flex gap-2">
            <label className="relative w-[42%] sm:w-48 shrink-0">
              <span className="sr-only">{t.placeLabel}</span>
              <select
                value={selectedRegion || ""}
                onChange={(e) => setSelectedRegion(e.target.value || null)}
                className="w-full min-h-[44px] appearance-none rounded-xl border border-gray-200 bg-white pl-3 pr-8 text-sm text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
              >
                <option value="">{t.anyPlace}</option>
                {placeOptions.map((p) => (
                  <option key={p.code} value={p.code}>{`${flagEmoji(p.code)} ${p.name}`}</option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" aria-hidden="true" />
            </label>
            <label className="relative flex-1 min-w-0">
              <span className="sr-only">{t.searchLabel}</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" aria-hidden="true" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t.searchPlaceholder}
                className="w-full min-h-[44px] rounded-xl border border-gray-200 pl-9 pr-10 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 [&::-webkit-search-cancel-button]:hidden"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  aria-label={t.clearSearch}
                  className="absolute right-0 top-0 h-11 w-11 flex items-center justify-center text-gray-400 hover:text-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 rounded-xl"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </label>
          </div>
        </div>
      </div>

      <section className="mt-4 rounded-2xl border border-gray-100 bg-white">
        <button
          type="button"
          onClick={() => setMapOpen((o) => !o)}
          aria-expanded={mapOpen}
          aria-controls="world-map-panel"
          className="flex w-full min-h-[44px] items-center justify-between gap-3 rounded-2xl px-4 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
        >
          <span className="flex items-center gap-2 text-sm font-semibold text-gray-800">
            <MapIcon className="h-4 w-4 text-purple-600" aria-hidden="true" />
            {t.exploreByPlace}
            {regionName && (
              <span className="font-normal text-gray-500">· {flagEmoji(selectedRegion)} {regionName}</span>
            )}
          </span>
          <span className="flex items-center gap-1 text-xs text-gray-500">
            {mapOpen ? t.hideMap : t.showMap}
            <ChevronDown className={`h-4 w-4 transition-transform motion-reduce:transition-none ${mapOpen ? "rotate-180" : ""}`} aria-hidden="true" />
          </span>
        </button>
        {mapOpen && (
          <div id="world-map-panel" className="px-2 pb-3 sm:px-4 sm:pb-4">
            <WorldMap onSelectRegion={setSelectedRegion} selectedRegion={selectedRegion} />
          </div>
        )}
      </section>

      {hasActiveFilters && (
        <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-gray-500">{t.showing}</span>
          {regionName && (
            <button
              type="button"
              onClick={() => setSelectedRegion(null)}
              aria-label={`${t.removeFilter}: ${regionName}`}
              className="inline-flex min-h-[44px] sm:min-h-0 items-center gap-1 rounded-full bg-purple-50 text-purple-700 pl-3 pr-2 py-1 font-medium hover:bg-purple-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
            >
              {flagEmoji(selectedRegion)} {regionName} <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
          {selectedCategory && (
            <button
              type="button"
              onClick={() => setSelectedCategory(null)}
              aria-label={`${t.removeFilter}: ${categoryLabel(selectedCategory)}`}
              className="inline-flex min-h-[44px] sm:min-h-0 items-center gap-1 rounded-full bg-purple-50 text-purple-700 pl-3 pr-2 py-1 font-medium hover:bg-purple-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
            >
              {categoryLabel(selectedCategory)} <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
          {debouncedSearch && (
            <button
              type="button"
              onClick={() => setSearch("")}
              aria-label={`${t.removeFilter}: ${debouncedSearch}`}
              className="inline-flex min-h-[44px] sm:min-h-0 items-center gap-1 rounded-full bg-purple-50 text-purple-700 pl-3 pr-2 py-1 font-medium hover:bg-purple-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
            >
              &ldquo;{debouncedSearch}&rdquo; <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            onClick={clearAll}
            className="min-h-[44px] sm:min-h-0 px-1 text-xs text-gray-500 underline hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 rounded"
          >
            {t.clearAll}
          </button>
        </div>
      )}

      <div className="sr-only" aria-live="polite">
        {status === "loading" || status === "loading-more" ? t.loadingMore : ""}
        {status === "error" || status === "error-more" ? t.errorTitle : ""}
      </div>

      <div className="mt-5 pb-12">
        {status === "error" ? (
          <div role="alert" className="mx-auto max-w-md rounded-2xl border border-amber-200 bg-amber-50 px-5 py-8 text-center">
            <p className="font-semibold text-gray-900">{t.errorTitle}</p>
            <p className="mt-1 text-sm text-gray-600">{t.errorBody}</p>
            <button
              type="button"
              onClick={() => loadPage(true)}
              className="mt-5 inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-purple-600 px-5 text-sm font-semibold text-white hover:bg-purple-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 focus-visible:ring-offset-2"
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" /> {t.retry}
            </button>
          </div>
        ) : status === "loading" ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-5">
            {Array.from({ length: 8 }, (_, i) => <FeatureCardSkeleton key={i} />)}
          </div>
        ) : features.length === 0 ? (
          <div className="mx-auto max-w-md rounded-2xl border border-gray-100 bg-gray-50/70 px-5 py-10 text-center">
            <Compass className="mx-auto h-8 w-8 text-purple-500" aria-hidden="true" />
            <p className="mt-3 font-semibold text-gray-900">{t.emptyTitle}</p>
            <p className="mt-1 text-sm text-gray-600">{hasActiveFilters ? t.emptyFiltered : t.emptyLibrary}</p>
            {hasActiveFilters && (
              <>
                <button
                  type="button"
                  onClick={clearAll}
                  className="mt-5 inline-flex min-h-[44px] items-center rounded-xl bg-purple-600 px-5 text-sm font-semibold text-white hover:bg-purple-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 focus-visible:ring-offset-2"
                >
                  {t.clearFilters}
                </button>
                <p className="mt-5 text-xs text-gray-500">{t.tryInstead}</p>
                <div className="mt-2 flex flex-wrap justify-center gap-2">
                  {suggestions.map((key) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => { setSelectedRegion(null); setSearch(""); setSelectedCategory(key); }}
                      className={chipClass(false)}
                    >
                      {categoryLabel(key)}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        ) : (
          <>
            <ul className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-5">
              {features.map((f) => (
                <li key={f.id}>
                  <FeatureCard feature={f} />
                </li>
              ))}
              {status === "loading-more" &&
                Array.from({ length: 4 }, (_, i) => (
                  <li key={`skeleton-${i}`}><FeatureCardSkeleton /></li>
                ))}
            </ul>

            <div ref={sentinelRef} aria-hidden="true" className="h-px" />

            {status === "error-more" && (
              <div role="alert" className="mt-6 flex flex-wrap items-center justify-center gap-3 text-sm text-gray-600">
                <span>{t.errorTitle}</span>
                <button
                  type="button"
                  onClick={() => loadPage(false)}
                  className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-gray-200 px-4 font-semibold text-gray-800 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
                >
                  <RefreshCw className="h-4 w-4" aria-hidden="true" /> {t.retry}
                </button>
              </div>
            )}

            {!hasMore && status === "idle" && (
              <p className="mt-10 text-center text-sm text-gray-500">{t.endOfFeed}</p>
            )}
          </>
        )}
      </div>
    </>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Clock3, Landmark, Pause, Play, Sparkles } from "lucide-react";
import type { WorldFeature, WorldTrend, WorldTrendsCoverage } from "@/lib/worldTypes";
import TrendFeed from "@/components/world/TrendFeed";
import FeatureCard from "@/components/world/FeatureCard";

const MS_PER_DAY = 24 * 60 * 60 * 1000;
// Real per-region trend coverage in this app only goes back to when that
// region's collector started (days_with_data below) — there is nothing in
// `trends` before June 2026 at all. A slider is still useful for a region
// with two or more real collection dates; regions with only one date remain
// in the "coverage just started" state instead of showing a misleading
// zero-width scrubber.
const MIN_DAYS_FOR_SCRUBBER = 2;

// Explicit locale, not the runtime default — this component is server-
// rendered for its initial HTML then hydrated client-side, and an implicit
// locale can differ between the two, breaking hydration (confirmed live
// for the same root cause in TrendFeed.tsx's likes formatting).
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function formatYear(year: number): string {
  return year < 0 ? `${Math.abs(year)} BCE` : `${year} CE`;
}

function chooseYearStep(span: number): number {
  if (span >= 1000) return 100;
  if (span >= 100) return 10;
  return 1;
}

function tickValues(min: number, max: number, count = 5): number[] {
  if (min === max) return [min];
  return Array.from({ length: count }, (_, index) => Math.round(min + ((max - min) * index) / (count - 1)));
}

interface Props {
  region: string;
  regionLabel: string;
  coverage: WorldTrendsCoverage;
  initialTrends: WorldTrend[];
}

export default function TimeCursor({ region, regionLabel, coverage, initialTrends }: Props) {
  const [mode, setMode] = useState<"recent" | "historical">("recent");
  const hasScrubbableCoverage = coverage.days_with_data >= MIN_DAYS_FOR_SCRUBBER && coverage.earliest && coverage.latest;

  const totalDays = useMemo(() => {
    if (!coverage.earliest || !coverage.latest) return 0;
    return Math.max(1, Math.round((new Date(coverage.latest).getTime() - new Date(coverage.earliest).getTime()) / MS_PER_DAY));
  }, [coverage]);

  const [dayOffset, setDayOffset] = useState(totalDays); // starts at "latest" (today)
  const [trends, setTrends] = useState<WorldTrend[]>(initialTrends);
  const [loadingTrends, setLoadingTrends] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [eraFeatures, setEraFeatures] = useState<WorldFeature[] | null>(null);
  const [loadingEra, setLoadingEra] = useState(false);
  const eraBounds = useMemo(() => {
    const years = (eraFeatures || []).map((feature) => feature.era_year).filter((year): year is number => year !== null);
    if (years.length === 0) return null;
    return { min: Math.min(...years), max: Math.max(...years) };
  }, [eraFeatures]);
  const eraStep = eraBounds ? chooseYearStep(eraBounds.max - eraBounds.min) : 1;
  const [eraYear, setEraYear] = useState(0);

  useEffect(() => {
    if (!isPlaying || !hasScrubbableCoverage) return;
    const timer = window.setInterval(() => {
      setDayOffset((current) => {
        const next = current >= totalDays ? 0 : current + 1;
        fetchTrendsAsOf(next);
        return next;
      });
    }, 1800);
    return () => window.clearInterval(timer);
  }, [isPlaying, hasScrubbableCoverage, totalDays]);

  useEffect(() => {
    if (eraBounds && eraYear === 0) setEraYear(eraBounds.max);
  }, [eraBounds, eraYear]);

  const selectedDate = useMemo(() => {
    if (!coverage.earliest) return null;
    return new Date(new Date(coverage.earliest).getTime() + dayOffset * MS_PER_DAY);
  }, [coverage.earliest, dayOffset]);

  async function fetchTrendsAsOf(offset: number) {
    if (!coverage.earliest) return;
    setLoadingTrends(true);
    try {
      const asOf = new Date(new Date(coverage.earliest).getTime() + (offset + 1) * MS_PER_DAY);
      const params = new URLSearchParams({ region, limit: "20", date_to: asOf.toISOString() });
      const res = await fetch(`/api/world/trends?${params.toString()}`);
      const data = await res.json().catch(() => ({}));
      setTrends(Array.isArray(data.trends) ? data.trends : []);
    } finally {
      setLoadingTrends(false);
    }
  }

  async function loadEraFeatures() {
    setLoadingEra(true);
    try {
      const params = new URLSearchParams({ region, era_only: "true", limit: "48" });
      const res = await fetch(`/api/world/features?${params.toString()}`);
      const data = await res.json().catch(() => ({}));
      setEraFeatures(Array.isArray(data.features) ? data.features : []);
    } finally {
      setLoadingEra(false);
    }
  }

  function selectRecent() {
    setMode("recent");
    setIsPlaying(false);
  }

  function selectHistorical() {
    setMode("historical");
    setIsPlaying(false);
    if (eraFeatures === null) loadEraFeatures();
  }

  function selectEraYear(year: number) {
    setEraYear(year);
  }

  const recentTicks = hasScrubbableCoverage && coverage.earliest && coverage.latest
    ? tickValues(0, totalDays).map((offset) => ({ offset, label: formatDate(new Date(new Date(coverage.earliest!).getTime() + offset * MS_PER_DAY).toISOString()) }))
    : [];
  const eraTicks = eraBounds ? tickValues(eraBounds.min, eraBounds.max) : [];
  const visibleEraFeatures = eraFeatures?.filter((feature) => {
    if (feature.era_year === null || !eraBounds) return false;
    const tolerance = Math.max(eraStep / 2, 1);
    return Math.abs(feature.era_year - eraYear) <= tolerance;
  }) || [];

  return (
    <div>
      <div className="rounded-3xl border border-purple-100 bg-gradient-to-br from-white via-purple-50/40 to-fuchsia-50/70 p-4 sm:p-6 mb-6 shadow-sm shadow-purple-100/60">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-purple-500">
              <Sparkles className="h-3.5 w-3.5" /> Explore time
            </div>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-2xl font-semibold tracking-tight text-gray-900">
                {mode === "recent" && hasScrubbableCoverage && selectedDate ? formatDate(selectedDate.toISOString()) : mode === "historical" && eraBounds ? formatYear(eraYear) : "No trend history yet"}
              </span>
              {mode === "recent" && hasScrubbableCoverage && (
                <button type="button" aria-label={isPlaying ? "Pause timeline" : "Play timeline"} onClick={() => setIsPlaying((playing) => !playing)} className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-purple-600 text-white shadow-sm transition hover:scale-105 hover:bg-purple-700">
                  {isPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="ml-0.5 h-3.5 w-3.5" />}
                </button>
              )}
            </div>
            <p className="mt-1 text-xs text-gray-500">
              {mode === "recent" ? (hasScrubbableCoverage ? `${coverage.days_with_data} collection days of real trend history` : coverage.days_with_data === 0 ? "No trend history yet for this region" : "Coverage has just started") : eraBounds ? `Browse a ${eraStep >= 100 ? "century" : eraStep >= 10 ? "decade" : "year"} at a time` : "Historical content will appear here as it is curated"}
            </p>
          </div>

          <div className="inline-flex w-fit rounded-full border border-purple-200 bg-white/80 p-1 text-xs font-semibold shadow-sm">
            <button type="button" onClick={selectRecent} className={`rounded-full px-3 py-1.5 transition ${mode === "recent" ? "bg-purple-600 text-white shadow-sm" : "text-gray-500 hover:text-purple-700"}`}><Clock3 className="mr-1.5 inline h-3.5 w-3.5" />Recent</button>
            <button type="button" onClick={selectHistorical} className={`rounded-full px-3 py-1.5 transition ${mode === "historical" ? "bg-purple-600 text-white shadow-sm" : "text-gray-500 hover:text-purple-700"}`}><Landmark className="mr-1.5 inline h-3.5 w-3.5" />Historical</button>
          </div>
        </div>

        {mode === "recent" && hasScrubbableCoverage && (
          <div className="mt-6">
            <input type="range" min={0} max={totalDays} step={1} value={dayOffset} onChange={(e) => { const next = Number(e.target.value); setDayOffset(next); fetchTrendsAsOf(next); }} className="h-2 w-full cursor-pointer appearance-none rounded-full bg-purple-200 accent-purple-600" aria-label="Browse recent trend history" />
            <div className="mt-2 flex justify-between gap-2 text-[10px] font-medium text-purple-400">
              {recentTicks.map((tick) => <span key={tick.offset} className="text-center">{tick.label}</span>)}
            </div>
            <div className="mt-3 flex items-center justify-between text-[11px] text-gray-400"><button type="button" onClick={() => { setDayOffset(Math.max(0, dayOffset - 1)); fetchTrendsAsOf(Math.max(0, dayOffset - 1)); }} className="inline-flex items-center gap-1 hover:text-purple-600"><ChevronLeft className="h-3.5 w-3.5" />Earlier</button><span>Today</span><button type="button" onClick={() => { setDayOffset(Math.min(totalDays, dayOffset + 1)); fetchTrendsAsOf(Math.min(totalDays, dayOffset + 1)); }} className="inline-flex items-center gap-1 hover:text-purple-600">Later<ChevronRight className="h-3.5 w-3.5" /></button></div>
          </div>
        )}

        {mode === "historical" && eraBounds && (
          <div className="mt-6">
            <input type="range" min={eraBounds.min} max={eraBounds.max} step={eraStep} value={Math.min(eraBounds.max, Math.max(eraBounds.min, eraYear))} onChange={(e) => selectEraYear(Number(e.target.value))} className="h-2 w-full cursor-pointer appearance-none rounded-full bg-fuchsia-200 accent-fuchsia-600" aria-label="Browse historical eras" />
            <div className="mt-2 flex justify-between gap-2 text-[10px] font-medium text-fuchsia-500">{eraTicks.map((tick) => <span key={tick} className="text-center">{formatYear(tick)}</span>)}</div>
          </div>
        )}
      </div>

      {mode === "recent" ? (
        loadingTrends ? (
          <p className="text-sm text-gray-400 py-6">Loading…</p>
        ) : trends.length > 0 ? (
          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Trending in {regionLabel}</h2>
            <TrendFeed trends={trends} />
          </section>
        ) : (
          <p className="text-sm text-gray-400 py-6">Nothing trending in {regionLabel} for this date.</p>
        )
      ) : loadingEra ? (
        <p className="text-sm text-gray-400 py-6">Loading…</p>
      ) : eraFeatures && visibleEraFeatures.length > 0 ? (
        <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
          {visibleEraFeatures.map((f) => (
            <FeatureCard key={f.id} feature={f} />
          ))}
        </section>
      ) : (
        <p className="text-sm text-gray-400 py-6">
          No historical-era Features published for {regionLabel} yet — check back soon.
        </p>
      )}
    </div>
  );
}

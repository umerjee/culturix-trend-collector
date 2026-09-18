"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Clock3, ExternalLink, Landmark, Pause, Play, Sparkles } from "lucide-react";
import type { WorldDigestLanguage, WorldFeature, WorldTrend, WorldTrendDigestGroup, WorldTrendsCoverage } from "@/lib/worldTypes";
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
  initialDigest: WorldTrendDigestGroup[];
}

export default function TimeCursor({ region, regionLabel, coverage, initialTrends, initialDigest }: Props) {
  const [mode, setMode] = useState<"recent" | "historical">("recent");
  const hasScrubbableCoverage = coverage.days_with_data >= MIN_DAYS_FOR_SCRUBBER && coverage.earliest && coverage.latest;

  const totalDays = useMemo(() => {
    if (!coverage.earliest || !coverage.latest) return 0;
    return Math.max(1, Math.round((new Date(coverage.latest).getTime() - new Date(coverage.earliest).getTime()) / MS_PER_DAY));
  }, [coverage]);

  const [dayOffset, setDayOffset] = useState(totalDays); // starts at "latest" (today)
  const [trends, setTrends] = useState<WorldTrend[]>(initialTrends);
  const [digest, setDigest] = useState<WorldTrendDigestGroup[]>(initialDigest);
  const [digestLanguage, setDigestLanguage] = useState<WorldDigestLanguage>("en");
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

  async function fetchDigest(language: WorldDigestLanguage, params: URLSearchParams) {
    const digestParams = new URLSearchParams(params);
    digestParams.set("lang", language);
    digestParams.set("limit", "8");
    const digestRes = await fetch(`/api/world/trends/digest?${digestParams.toString()}`);
    const digestData = await digestRes.json().catch(() => ({}));
    setDigest(Array.isArray(digestData.groups) ? digestData.groups : []);
  }

  async function fetchTrendsAsOf(offset: number, language = digestLanguage) {
    if (!coverage.earliest) return;
    setLoadingTrends(true);
    try {
      const asOf = new Date(new Date(coverage.earliest).getTime() + (offset + 1) * MS_PER_DAY);
      const params = new URLSearchParams({ region, limit: "20", date_to: asOf.toISOString() });
      const res = await fetch(`/api/world/trends?${params.toString()}`);
      const data = await res.json().catch(() => ({}));
      setTrends(Array.isArray(data.trends) ? data.trends : []);
      await fetchDigest(language, params);
    } finally {
      setLoadingTrends(false);
    }
  }

  function changeDigestLanguage(language: WorldDigestLanguage) {
    setDigestLanguage(language);
    const params = new URLSearchParams({ region, limit: "20" });
    if (coverage.earliest && selectedDate) params.set("date_to", new Date(selectedDate.getTime() + MS_PER_DAY).toISOString());
    fetchDigest(language, params);
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
        ) : digest.length > 0 ? (
          <section>
            <div className="mb-5 flex items-end justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">What is moving in {regionLabel}</h2>
                <p className="mt-1 text-sm text-gray-500">Themes first, with the original signals underneath for context.</p>
              </div>
              <div className="flex items-center gap-3">
                <label className="sr-only" htmlFor="digest-language">Digest language</label>
                <select id="digest-language" value={digestLanguage} onChange={(event) => changeDigestLanguage(event.target.value as WorldDigestLanguage)} className="rounded-full border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-600 outline-none focus:border-purple-400">
                  <option value="en">English</option>
                  <option value="fr">Français</option>
                  <option value="es">Español</option>
                </select>
                <span className="hidden text-xs text-gray-400 sm:block">{digest.length} themes</span>
              </div>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              {digest.map((group) => (
                <article key={group.id} className="rounded-2xl border border-gray-100 bg-white p-5 shadow-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${group.kind === "cluster" ? "bg-purple-50 text-purple-600" : "bg-gray-100 text-gray-500"}`}>
                          {group.kind === "cluster" ? "Theme" : "Automatic topic group"}
                        </span>
                        {group.momentum && <span className="text-[11px] font-semibold text-emerald-600">{group.momentum === "up" ? "Growing" : group.momentum === "down" ? "Cooling" : "Steady"}</span>}
                      </div>
                      <h3 className="text-base font-semibold text-gray-900">{group.title}</h3>
                    </div>
                    <span className="shrink-0 text-xs text-gray-400">{group.signal_count} signals</span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-gray-600">{group.summary}</p>
                  <div className="mt-4 space-y-2 border-t border-gray-100 pt-3">
                    {group.signals.map((signal) => (
                      <div key={`${signal.platform}-${signal.id}`} className="flex items-center gap-2 text-xs text-gray-500">
                        <span className="font-semibold text-gray-700">{signal.platform.replace("_", " ")}</span>
                        <span className="min-w-0 flex-1 truncate">{signal.title || "Untitled signal"}</span>
                        {signal.url && <a href={signal.url} target="_blank" rel="noopener noreferrer" aria-label="Open source signal" className="text-gray-400 hover:text-purple-600"><ExternalLink className="h-3 w-3" /></a>}
                      </div>
                    ))}
                  </div>
                </article>
              ))}
            </div>
            <details className="mt-6 rounded-xl border border-gray-100 bg-gray-50/60 p-4">
              <summary className="cursor-pointer text-sm font-medium text-gray-600">Show raw source feed ({trends.length})</summary>
              <div className="mt-4"><TrendFeed trends={trends} /></div>
            </details>
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

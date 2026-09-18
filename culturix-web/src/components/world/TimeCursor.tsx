"use client";

import { useMemo, useState } from "react";
import { Clock, Landmark } from "lucide-react";
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
  const [eraFeatures, setEraFeatures] = useState<WorldFeature[] | null>(null);
  const [loadingEra, setLoadingEra] = useState(false);

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

  function selectHistorical() {
    setMode("historical");
    if (eraFeatures === null) loadEraFeatures();
  }

  return (
    <div>
      <div className="rounded-2xl border border-gray-100 p-4 sm:p-5 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <Clock className="h-4 w-4 text-purple-500 shrink-0" />
          {mode === "recent" && hasScrubbableCoverage && selectedDate ? (
            <span className="text-sm font-medium text-gray-700">{formatDate(selectedDate.toISOString())}</span>
          ) : mode === "recent" ? (
            <span className="text-sm font-medium text-gray-400">
              {coverage.days_with_data === 0 ? "No trend history yet for this region" : "Coverage just started — not enough days for a timeline yet"}
            </span>
          ) : (
            <span className="text-sm font-medium text-gray-700">Historical eras</span>
          )}
        </div>

        {hasScrubbableCoverage && (
          <input
            type="range"
            min={0}
            max={totalDays}
            step={1}
            value={mode === "recent" ? dayOffset : totalDays}
            onChange={(e) => {
              const next = Number(e.target.value);
              setMode("recent");
              setDayOffset(next);
              fetchTrendsAsOf(next);
            }}
            className="w-full accent-purple-600"
          />
        )}

        <div className="flex items-center justify-between mt-2 text-[11px] text-gray-400">
          {hasScrubbableCoverage ? (
            <>
              <span>{formatDate(coverage.earliest!)}</span>
              <span>Today</span>
            </>
          ) : (
            <span />
          )}
          <button
            type="button"
            onClick={selectHistorical}
            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
              mode === "historical"
                ? "bg-purple-600 border-purple-600 text-white"
                : "border-gray-200 text-gray-500 hover:border-purple-300 hover:text-purple-600"
            }`}
          >
            <Landmark className="h-3 w-3" /> Historical eras
          </button>
        </div>
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
      ) : eraFeatures && eraFeatures.length > 0 ? (
        <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
          {eraFeatures.map((f) => (
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

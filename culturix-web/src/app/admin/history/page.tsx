"use client";

import { useEffect, useState } from "react";
import { fetchAdminData, fetchAdminDetail } from "@/lib/admin/fetchAdmin";
import type { TrendTheme, TrendOccurrence } from "@/lib/admin/types";
import { fmt } from "@/lib/admin/types";
import { PatternBadge, PATTERN_ORDER } from "@/components/admin/badges";
import WeekdayBarChart, { WEEKDAYS, WEEKDAYS_FULL } from "@/components/admin/charts/WeekdayBarChart";
import OccurrenceTimeline from "@/components/admin/charts/OccurrenceTimeline";

export default function HistoryPage() {
  const [trendHistory, setTrendHistory] = useState<TrendTheme[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedThemeId, setSelectedThemeId] = useState<number | null>(null);
  const [occurrences, setOccurrences] = useState<TrendOccurrence[]>([]);
  const [occurrencesLoading, setOccurrencesLoading] = useState(false);

  useEffect(() => {
    fetchAdminData<TrendTheme[]>("trend-history").then(setTrendHistory).catch(() => setTrendHistory([])).finally(() => setLoading(false));
  }, []);

  async function selectTheme(id: number) {
    setSelectedThemeId(id);
    setOccurrencesLoading(true);
    try {
      const data = await fetchAdminDetail<TrendOccurrence[]>("trend-history-occurrences", id);
      setOccurrences(Array.isArray(data) ? data : []);
    } catch {
      setOccurrences([]);
    } finally {
      setOccurrencesLoading(false);
    }
  }

  if (loading) return <p className="text-sm text-gray-400 text-center py-16">Loading…</p>;

  const theme = trendHistory.find((t) => t.id === selectedThemeId) ?? null;

  return (
    <div className="space-y-6">
      <h1 className="font-bold text-gray-900 text-xl">History</h1>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {PATTERN_ORDER.map((p) => (
          <div key={p} className="bg-white rounded-xl border border-gray-100 p-4">
            <p className="text-2xl font-bold text-gray-900">
              {trendHistory.filter((t) => (t.recurrence_pattern ?? "unclear") === p).length}
            </p>
            <PatternBadge pattern={p} />
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-[1fr,1.2fr] gap-6 items-start lg:h-[calc(100vh-20rem)]">
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden lg:h-full lg:flex lg:flex-col">
          <div className="px-6 py-4 border-b border-gray-50 flex items-center justify-between shrink-0">
            <h2 className="font-semibold text-gray-900 text-sm">Trend themes</h2>
            <span className="text-xs text-gray-400">{trendHistory.length} tracked</span>
          </div>
          <ul className="divide-y divide-gray-50 overflow-y-auto lg:flex-1">
            {trendHistory.length === 0 && (
              <li className="px-6 py-10 text-center text-sm text-gray-400">
                No trend history yet — it accumulates as the daily pipeline runs.
              </li>
            )}
            {trendHistory
              .slice()
              .sort((a, b) => (b.last_seen_at ?? "").localeCompare(a.last_seen_at ?? ""))
              .map((t) => (
                <li key={t.id}>
                  <button
                    onClick={() => selectTheme(t.id)}
                    className={`w-full text-left px-6 py-3.5 transition-colors ${
                      selectedThemeId === t.id ? "bg-primary-50" : "hover:bg-gray-50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium text-gray-900 truncate">{t.canonical_name}</p>
                      <PatternBadge pattern={t.recurrence_pattern} />
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1 text-xs text-gray-400">
                      <span>{t.occurrence_count} occurrence{t.occurrence_count !== 1 ? "s" : ""}</span>
                      <span>·</span>
                      <span>last seen {fmt(t.last_seen_at)}</span>
                      {t.recurrence_pattern === "weekly" && t.dominant_day_of_week != null && (
                        <>
                          <span>·</span>
                          <span>usually {WEEKDAYS_FULL[t.dominant_day_of_week]}</span>
                        </>
                      )}
                    </div>
                  </button>
                </li>
              ))}
          </ul>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-6 lg:h-full lg:overflow-y-auto">
          {!selectedThemeId && (
            <p className="text-sm text-gray-400 text-center py-16">Select a trend to see its history.</p>
          )}
          {selectedThemeId && occurrencesLoading && (
            <p className="text-sm text-gray-400 text-center py-16">Loading…</p>
          )}
          {selectedThemeId && !occurrencesLoading && theme && (
            <div className="space-y-6">
              <div>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-semibold text-gray-900">{theme.canonical_name}</h3>
                    {theme.description && <p className="text-sm text-gray-500 mt-1">{theme.description}</p>}
                  </div>
                  <PatternBadge pattern={theme.recurrence_pattern} />
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-xs text-gray-400">
                  <span>First seen {fmt(theme.first_seen_at)}</span>
                  <span>Last seen {fmt(theme.last_seen_at)}</span>
                  <span>{theme.occurrence_count} occurrences</span>
                  {theme.pattern_confidence != null && <span>{Math.round(theme.pattern_confidence * 100)}% confidence</span>}
                </div>
              </div>

              <div>
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Occurrences by day of week</p>
                <WeekdayBarChart occurrences={occurrences} dominantDay={theme.dominant_day_of_week} />
              </div>

              <div>
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-4">Timeline</p>
                <OccurrenceTimeline occurrences={occurrences} />
              </div>

              <div>
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Occurrence log</p>
                <div className="border border-gray-100 rounded-lg overflow-hidden max-h-56 overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-gray-50 sticky top-0">
                      <tr>
                        <th className="text-left px-4 py-2 font-semibold text-gray-500">Date</th>
                        <th className="text-left px-4 py-2 font-semibold text-gray-500">Day</th>
                        <th className="text-left px-4 py-2 font-semibold text-gray-500">Size</th>
                        <th className="text-left px-4 py-2 font-semibold text-gray-500">Durability</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {occurrences
                        .slice()
                        .sort((a, b) => b.occurrence_date.localeCompare(a.occurrence_date))
                        .map((o) => (
                          <tr key={o.id}>
                            <td className="px-4 py-2 text-gray-700 whitespace-nowrap">{o.occurrence_date}</td>
                            <td className="px-4 py-2 text-gray-500">{WEEKDAYS[o.day_of_week]}</td>
                            <td className="px-4 py-2 text-gray-500">{o.size ?? "—"}</td>
                            <td className="px-4 py-2 text-gray-500 capitalize">{o.durability ?? "—"}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

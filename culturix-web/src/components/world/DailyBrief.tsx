"use client";

import { useEffect, useState } from "react";
import { CalendarDays, Newspaper, TrendingDown, TrendingUp } from "lucide-react";
import type { WorldDigestLanguage, WorldRegionSummary } from "@/lib/worldTypes";

const MOOD_STYLES: Record<string, string> = {
  celebratory: "bg-amber-50 text-amber-700",
  playful: "bg-pink-50 text-pink-700",
  curious: "bg-sky-50 text-sky-700",
  tense: "bg-orange-50 text-orange-700",
  somber: "bg-slate-100 text-slate-600",
  angry: "bg-red-50 text-red-700",
  neutral: "bg-gray-100 text-gray-600",
};

// Explicit locale: this renders on the server first, and an implicit locale
// can differ from the browser's and break hydration.
function formatDay(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

interface Props {
  region: string;
  regionLabel: string;
  // ISO date (YYYY-MM-DD) to show, or null for the latest available brief.
  date: string | null;
  language: WorldDigestLanguage;
  initial?: WorldRegionSummary | null;
}

// A short daily brief for the country: calendar + what people engaged with,
// compared with the news and with the country's usual. Renders nothing when
// there is no brief for the day (thin-data regions).
export default function DailyBrief({ region, regionLabel, date, language, initial = null }: Props) {
  const [brief, setBrief] = useState<WorldRegionSummary | null>(initial);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // The server already rendered the latest brief in English.
    if (initial && date === null && language === "en") { setBrief(initial); return; }
    const controller = new AbortController();
    const params = new URLSearchParams({ lang: language });
    if (date) params.set("date", date);
    setLoading(true);
    fetch(`/api/world/regions/${region}/summary?${params.toString()}`, { signal: controller.signal })
      .then((res) => res.json())
      .then((data) => setBrief(data && "summary" in data ? data : null))
      .catch(() => { if (!controller.signal.aborted) setBrief(null); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [region, date, language, initial]);

  if (!brief?.summary) return loading ? <div className="mb-6 h-24 animate-pulse rounded-2xl bg-gray-50" /> : null;

  const events = brief.calendar.filter((e) => e.when === "today").concat(brief.calendar.filter((e) => e.when !== "today")).slice(0, 3);
  return (
    <section aria-label={`Daily brief for ${regionLabel}`} className={`mb-6 rounded-2xl border border-purple-100 bg-gradient-to-br from-white to-purple-50/50 p-4 sm:p-5 transition-opacity ${loading ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-[11px] font-bold uppercase tracking-[0.16em] text-purple-500">
          {brief.date ? `${regionLabel} · ${formatDay(brief.date)}` : `${regionLabel} daily brief`}
        </h2>
        {brief.mood && (
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${MOOD_STYLES[brief.mood] || MOOD_STYLES.neutral}`}>{brief.mood}</span>
        )}
        {brief.vs_usual === "busier" && <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600"><TrendingUp className="h-3 w-3" /> busier than usual</span>}
        {brief.vs_usual === "quieter" && <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-500"><TrendingDown className="h-3 w-3" /> quieter than usual</span>}
        {brief.alignment && brief.alignment !== "unknown" && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-gray-500"><Newspaper className="h-3 w-3" /> news and social {brief.alignment === "aligned" ? "aligned" : "differ"}</span>
        )}
      </div>

      <p className="mt-2 text-base leading-relaxed text-gray-800">{brief.summary}</p>

      {events.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {events.map((e) => (
            <li key={`${e.name}-${e.date}`} className="inline-flex items-center gap-1.5 rounded-full border border-purple-100 bg-white px-2.5 py-1 text-xs text-gray-600">
              <CalendarDays className="h-3 w-3 text-purple-400" />
              <span className="font-medium text-gray-800">{e.name}</span>
              <span className="text-gray-400">{e.when}</span>
            </li>
          ))}
        </ul>
      )}

      {brief.source !== "calendar" && brief.signal_count > 0 && (
        <p className="mt-3 text-[11px] text-gray-400">
          From {brief.signal_count.toLocaleString("en-US")} posts across {brief.platforms.slice(0, 4).map((p) => p.replace("_", " ")).join(", ")}
          {brief.source === "ai" ? ", read against live news headlines and this country's recent history." : "."}
        </p>
      )}
    </section>
  );
}

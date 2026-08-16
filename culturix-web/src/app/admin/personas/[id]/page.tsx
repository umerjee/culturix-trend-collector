"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Lightbulb } from "lucide-react";
import { fetchAdminDetail } from "@/lib/admin/fetchAdmin";
import type { PersonaDetail, TrendOccurrence } from "@/lib/admin/types";
import { fmt } from "@/lib/admin/types";
import { MomentumBadge, PlatformBadge } from "@/components/admin/badges";
import WeekdayBarChart from "@/components/admin/charts/WeekdayBarChart";
import OccurrenceTimeline from "@/components/admin/charts/OccurrenceTimeline";

export default function PersonaDetailPage({ params }: { params: { id: string } }) {
  const [detail, setDetail] = useState<PersonaDetail | null>(null);
  const [occurrences, setOccurrences] = useState<TrendOccurrence[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchAdminDetail<PersonaDetail>("persona-detail", params.id),
      fetchAdminDetail<TrendOccurrence[]>("persona-occurrences", params.id).catch(() => []),
    ])
      .then(([d, o]) => { setDetail(d); setOccurrences(Array.isArray(o) ? o : []); })
      .catch(() => { setDetail(null); setOccurrences([]); })
      .finally(() => setLoading(false));
  }, [params.id]);

  if (loading) return <p className="text-sm text-gray-400 text-center py-16">Loading…</p>;
  if (!detail) return <p className="text-sm text-gray-400 text-center py-16">Persona not found.</p>;

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-semibold text-gray-900">{detail.name}</h3>
          <MomentumBadge momentum={detail.momentum} />
        </div>
        <p className="text-sm text-gray-500 mt-1">{detail.description}</p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-xs text-gray-400">
          {detail.status && <span className="capitalize">{detail.status}</span>}
          {detail.first_seen_at && <span>First seen {fmt(detail.first_seen_at)}</span>}
          {detail.last_seen_at && <span>Last seen {fmt(detail.last_seen_at)}</span>}
        </div>
      </div>

      {occurrences.length > 0 && (
        <>
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Occurrences by day of week</p>
            <WeekdayBarChart occurrences={occurrences} dominantDay={null} />
          </div>
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-4">Timeline</p>
            <OccurrenceTimeline occurrences={occurrences} />
          </div>
        </>
      )}

      {detail.content_suggestions && detail.content_suggestions.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1.5">
            <Lightbulb className="h-3.5 w-3.5 text-amber-500" /> Content ideas
          </p>
          <div className="grid gap-2.5">
            {detail.content_suggestions.map((s, i) => (
              <div key={i} className="rounded-lg border border-gray-100 p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium text-gray-800 leading-snug">{s.title}</p>
                  <span className="shrink-0 text-xs text-gray-400">{s.format}</span>
                </div>
                {s.hook && <p className="text-xs text-gray-500 mt-1">{s.hook}</p>}
                <p className="text-xs font-medium text-primary-600 mt-1">{s.platform}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.sample_trends && detail.sample_trends.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Linked trends</p>
          <div className="divide-y divide-gray-50 border border-gray-100 rounded-lg overflow-hidden">
            {detail.sample_trends.map((t) => (
              <div key={t.id} className="flex items-center gap-3 px-4 py-3">
                <PlatformBadge platform={t.platform} />
                <span className="flex-1 text-sm text-gray-700 truncate">{t.title}</span>
                {t.url && (
                  <a href={t.url} target="_blank" rel="noreferrer" className="text-primary-600 hover:text-primary-800 shrink-0">
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

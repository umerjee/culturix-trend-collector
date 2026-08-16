"use client";

import { useEffect, useState } from "react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import type { Trend } from "@/lib/admin/types";
import { fmt } from "@/lib/admin/types";
import { PlatformBadge } from "@/components/admin/badges";

const PAGE_SIZE = 200;

export default function TrendsPage() {
  const [trends, setTrends] = useState<Trend[]>([]);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [platformFilter, setPlatformFilter] = useState("all");
  const [search, setSearch] = useState("");

  useEffect(() => {
    setLoading(true);
    fetchAdminData<Trend[]>("trends", { limit })
      .then(setTrends)
      .catch(() => setTrends([]))
      .finally(() => { setLoading(false); setLoadingMore(false); });
  }, [limit]);

  const byPlatform = trends.reduce<Record<string, number>>((acc, t) => {
    acc[t.platform] = (acc[t.platform] ?? 0) + 1;
    return acc;
  }, {});

  const filtered = trends.filter((t) => {
    if (platformFilter !== "all" && t.platform !== platformFilter) return false;
    if (search && !t.content.toLowerCase().includes(search.toLowerCase()) &&
        !(t.author ?? "").toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  if (loading && trends.length === 0) {
    return <p className="text-sm text-gray-400 text-center py-16">Loading trends…</p>;
  }

  return (
    <div className="space-y-4">
      <h1 className="font-bold text-gray-900 text-xl">Trends</h1>

      <div className="flex gap-3 flex-wrap items-center">
        <select
          value={platformFilter}
          onChange={(e) => setPlatformFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white"
        >
          <option value="all">All platforms</option>
          {Object.keys(byPlatform).map((p) => (
            <option key={p} value={p}>{p} ({byPlatform[p]})</option>
          ))}
        </select>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter by keyword or author…"
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white min-w-[16rem]"
        />
        <span className="text-sm text-gray-400 self-center">{filtered.length} of {trends.length} loaded</span>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-50 bg-gray-50">
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Platform</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Content</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Engagement</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Collected</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {filtered.map((t) => (
              <tr key={t.id} className="hover:bg-gray-50">
                <td className="px-6 py-3"><PlatformBadge platform={t.platform} /></td>
                <td className="px-6 py-3 max-w-sm">
                  {t.url ? (
                    <a href={t.url} target="_blank" rel="noreferrer" className="text-gray-800 hover:text-primary-600 line-clamp-2">
                      {t.content}
                    </a>
                  ) : (
                    <span className="text-gray-800 line-clamp-2">{t.content}</span>
                  )}
                </td>
                <td className="px-6 py-3 text-gray-400 whitespace-nowrap text-xs">
                  ♥ {(t.likes ?? 0).toLocaleString()} &middot; 💬 {(t.comments ?? 0).toLocaleString()}
                </td>
                <td className="px-6 py-3 text-gray-400 text-xs whitespace-nowrap">{fmt(t.collected_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {trends.length >= limit && (
        <div className="text-center">
          <button
            onClick={() => { setLoadingMore(true); setLimit((l) => l + PAGE_SIZE); }}
            disabled={loadingMore}
            className="px-4 py-2 border border-gray-200 text-gray-600 text-sm rounded-lg hover:bg-gray-50 disabled:opacity-50 transition"
          >
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}

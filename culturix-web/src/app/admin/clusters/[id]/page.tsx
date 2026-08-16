"use client";

import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import { fetchAdminDetail } from "@/lib/admin/fetchAdmin";
import type { ClusterDetail } from "@/lib/admin/types";
import { fmt } from "@/lib/admin/types";
import { PlatformBadge } from "@/components/admin/badges";

export default function ClusterDetailPage({ params }: { params: { id: string } }) {
  const [detail, setDetail] = useState<ClusterDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchAdminDetail<ClusterDetail>("cluster-detail", params.id)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [params.id]);

  if (loading) return <p className="text-sm text-gray-400 text-center py-16">Loading…</p>;
  if (!detail) return <p className="text-sm text-gray-400 text-center py-16">Cluster not found.</p>;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="font-semibold text-gray-900">{detail.theme || "Cluster"}</h3>
        {detail.summary && <p className="text-sm text-gray-500 mt-1">{detail.summary}</p>}
      </div>
      <div className="divide-y divide-gray-50 border border-gray-100 rounded-lg overflow-hidden max-h-[420px] overflow-y-auto">
        {detail.trends.length === 0 && (
          <p className="px-4 py-6 text-center text-xs text-gray-400">No trends linked yet.</p>
        )}
        {detail.trends.map((t) => (
          <div key={t.id} className="flex items-center gap-3 px-4 py-3">
            <PlatformBadge platform={t.platform} />
            <span className="flex-1 text-sm text-gray-700 truncate">{t.title}</span>
            <span className="text-xs text-gray-400 whitespace-nowrap">{fmt(t.collected_at)}</span>
            {t.url && (
              <a href={t.url} target="_blank" rel="noreferrer" className="text-primary-600 hover:text-primary-800 shrink-0">
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

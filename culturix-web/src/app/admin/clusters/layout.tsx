"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import type { Cluster } from "@/lib/admin/types";
import { fmt } from "@/lib/admin/types";
import { MomentumBadge } from "@/components/admin/badges";

export default function ClustersLayout({ children }: { children: React.ReactNode }) {
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [loading, setLoading] = useState(true);
  const pathname = usePathname();

  useEffect(() => {
    fetchAdminData<Cluster[]>("clusters").then(setClusters).catch(() => setClusters([])).finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="font-bold text-gray-900 text-xl">Clusters</h1>
      <div className="grid lg:grid-cols-[1fr,1.1fr] gap-6 items-start lg:h-[calc(100vh-14rem)]">
        <div className="space-y-3 lg:h-full lg:overflow-y-auto lg:pr-1">
          {loading && <p className="text-gray-400 text-sm">Loading…</p>}
          {!loading && clusters.length === 0 && (
            <p className="text-gray-400 text-sm">No clusters yet — run the pipeline first.</p>
          )}
          {clusters.map((c) => {
            const active = pathname === `/admin/clusters/${c.id}`;
            return (
              <Link
                key={c.id}
                href={`/admin/clusters/${c.id}`}
                className={`block w-full text-left bg-white rounded-xl border px-6 py-5 flex items-start justify-between gap-6 transition-colors ${
                  active ? "border-primary-300 ring-1 ring-primary-100" : "border-gray-100 hover:border-gray-200"
                }`}
              >
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-gray-900">{c.description || `Cluster ${c.label}`}</p>
                  <div className="flex items-center gap-3 mt-1.5">
                    <span className="text-xs text-gray-400">{fmt(c.created_at)}</span>
                    <MomentumBadge momentum={c.momentum} />
                  </div>
                </div>
                <span className="text-xs text-gray-500 whitespace-nowrap shrink-0 bg-gray-50 px-3 py-1 rounded-full">
                  {c.trend_count ?? 0} trends
                </span>
              </Link>
            );
          })}
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-6 lg:h-full lg:overflow-y-auto">
          {children}
        </div>
      </div>
    </div>
  );
}

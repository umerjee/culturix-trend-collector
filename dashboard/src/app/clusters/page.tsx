"use client";

import useSWR from "swr";
import Link from "next/link";
import { fetcher, api, type Cluster } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { PlatformBadge } from "@/components/ui/badge";
import { Network } from "lucide-react";

export default function ClustersPage() {
  const { data: clusters, isLoading, error } = useSWR<Cluster[]>(api.clusters(), fetcher);

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Clusters</h1>
        <p className="text-muted-foreground mt-1">Semantically grouped trend themes</p>
      </div>

      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-40 rounded-lg bg-gray-100 animate-pulse" />
          ))}
        </div>
      )}

      {error && <p className="text-red-600 text-sm">Failed to load clusters.</p>}

      {clusters && clusters.length === 0 && (
        <div className="text-center py-20 text-muted-foreground">
          <Network className="h-10 w-10 mx-auto mb-3 opacity-30" />
          <p>No clusters yet. Hit <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">POST /process/cluster</code> to generate them.</p>
        </div>
      )}

      {clusters && clusters.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {clusters.map((c) => (
            <Link key={c.id} href={`/clusters/${c.id}`}>
              <Card className="h-full hover:shadow-md transition-shadow cursor-pointer">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-base leading-snug">{c.theme ?? `Cluster ${c.label}`}</CardTitle>
                    <span className="shrink-0 rounded-full bg-violet-50 text-violet-700 text-xs font-semibold px-2 py-0.5">
                      {c.size} trends
                    </span>
                  </div>
                  {c.summary && <CardDescription className="text-sm line-clamp-2">{c.summary}</CardDescription>}
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1.5">
                    {c.sample_trends.slice(0, 3).map((t) => (
                      <div key={t.id} className="flex items-center gap-1.5 rounded-md bg-gray-50 border px-2 py-1">
                        <PlatformBadge platform={t.platform} />
                        <span className="text-xs text-gray-700 line-clamp-1 max-w-[140px]">{t.title}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

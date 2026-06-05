"use client";

import { use } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetcher, api, type ClusterDetail } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PlatformBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/utils";
import { ArrowLeft, ExternalLink } from "lucide-react";

export default function ClusterDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: cluster, isLoading, error } = useSWR<ClusterDetail>(api.cluster(Number(id)), fetcher);

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <Link href="/clusters">
        <Button variant="ghost" size="sm" className="mb-4 -ml-2">
          <ArrowLeft className="h-4 w-4 mr-1" /> Clusters
        </Button>
      </Link>

      {isLoading && <div className="h-32 rounded-lg bg-gray-100 animate-pulse" />}
      {error && <p className="text-red-600 text-sm">Failed to load cluster.</p>}

      {cluster && (
        <>
          <div className="mb-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h1 className="text-2xl font-bold">{cluster.theme ?? `Cluster ${cluster.label}`}</h1>
                {cluster.summary && <p className="text-muted-foreground mt-1">{cluster.summary}</p>}
              </div>
              <span className="shrink-0 rounded-full bg-violet-50 text-violet-700 text-sm font-semibold px-3 py-1">
                {cluster.size} trends
              </span>
            </div>
          </div>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Trends in this cluster</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ul className="divide-y">
                {cluster.trends.map((t) => (
                  <li key={t.id} className="flex items-center gap-3 px-6 py-3">
                    <PlatformBadge platform={t.platform} />
                    <span className="text-sm flex-1 line-clamp-1">{t.title}</span>
                    <span className="text-xs text-muted-foreground whitespace-nowrap">{formatDate(t.collected_at)}</span>
                    {t.url && (
                      <a href={t.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:text-blue-800">
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

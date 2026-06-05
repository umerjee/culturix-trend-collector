"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, api, type Trend } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PlatformBadge } from "@/components/ui/badge";
import { formatDate, formatNumber } from "@/lib/utils";
import { ExternalLink, ThumbsUp, MessageSquare } from "lucide-react";

const PLATFORMS = ["all", "twitter", "tiktok", "youtube"];
const PAGE_SIZE = 30;

export default function TrendsPage() {
  const [platform, setPlatform] = useState("all");
  const [page, setPage] = useState(0);

  const url = api.trends({
    platform: platform === "all" ? undefined : platform,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const { data: trends, isLoading, error } = useSWR<Trend[]>(url, fetcher);

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Trends</h1>
        <p className="text-muted-foreground mt-1">Latest signals from across platforms</p>
      </div>

      {/* Platform filter */}
      <div className="flex gap-2 mb-6">
        {PLATFORMS.map((p) => (
          <Button
            key={p}
            variant={platform === p ? "default" : "outline"}
            size="sm"
            onClick={() => { setPlatform(p); setPage(0); }}
            className="capitalize"
          >
            {p}
          </Button>
        ))}
      </div>

      {isLoading && (
        <div className="grid gap-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-16 rounded-lg bg-gray-100 animate-pulse" />
          ))}
        </div>
      )}

      {error && (
        <p className="text-red-600 text-sm">Failed to load trends. Is the API running?</p>
      )}

      {trends && (
        <>
          <div className="grid gap-2">
            {trends.map((t) => (
              <Card key={t.id} className="hover:shadow-md transition-shadow">
                <CardContent className="p-4">
                  <div className="flex items-start gap-3">
                    <PlatformBadge platform={t.platform} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium line-clamp-1">
                        {t.title || t.translated_content || t.content}
                      </p>
                      {t.translated_content && t.language !== "en" && (
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                          [{t.language}] {t.content?.slice(0, 80)}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-4 shrink-0 text-xs text-muted-foreground">
                      {t.likes != null && (
                        <span className="flex items-center gap-1">
                          <ThumbsUp className="h-3 w-3" /> {formatNumber(t.likes)}
                        </span>
                      )}
                      {t.comments != null && (
                        <span className="flex items-center gap-1">
                          <MessageSquare className="h-3 w-3" /> {formatNumber(t.comments)}
                        </span>
                      )}
                      <span>{formatDate(t.collected_at)}</span>
                      {t.url && (
                        <a href={t.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:text-blue-800">
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-6">
            <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              ← Previous
            </Button>
            <span className="text-sm text-muted-foreground">Page {page + 1}</span>
            <Button
              variant="outline"
              size="sm"
              disabled={trends.length < PAGE_SIZE}
              onClick={() => setPage((p) => p + 1)}
            >
              Next →
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

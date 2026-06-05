"use client";

import { useState, useCallback } from "react";
import useSWR from "swr";
import { fetcher, api, type Trend } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PlatformBadge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import { Search, ExternalLink } from "lucide-react";

const PLATFORMS = ["all", "twitter", "tiktok", "youtube"];

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [platform, setPlatform] = useState("all");

  const url =
    submitted.length >= 2
      ? api.search(submitted, platform === "all" ? undefined : platform)
      : null;

  const { data: results, isLoading, error } = useSWR<Trend[]>(url, fetcher);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (query.trim().length >= 2) setSubmitted(query.trim());
    },
    [query]
  );

  return (
    <div className="p-8 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Search</h1>
        <p className="text-muted-foreground mt-1">Find trends by keyword</p>
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2 mb-4">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. AI, sports, music..."
          className="flex-1"
        />
        <Button type="submit" disabled={query.length < 2}>
          <Search className="h-4 w-4 mr-1" /> Search
        </Button>
      </form>

      <div className="flex gap-2 mb-6">
        {PLATFORMS.map((p) => (
          <Button
            key={p}
            variant={platform === p ? "default" : "outline"}
            size="sm"
            onClick={() => setPlatform(p)}
            className="capitalize"
          >
            {p}
          </Button>
        ))}
      </div>

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-14 rounded-lg bg-gray-100 animate-pulse" />
          ))}
        </div>
      )}

      {error && <p className="text-red-600 text-sm">Search failed. Is the API running?</p>}

      {results && results.length === 0 && (
        <p className="text-muted-foreground text-sm text-center py-12">
          No results for &ldquo;{submitted}&rdquo;
        </p>
      )}

      {results && results.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground mb-3">{results.length} results for &ldquo;{submitted}&rdquo;</p>
          {results.map((t) => (
            <Card key={t.id} className="hover:shadow-sm transition-shadow">
              <CardContent className="p-4 flex items-center gap-3">
                <PlatformBadge platform={t.platform} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium line-clamp-1">{t.title || t.translated_content || t.content}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{formatDate(t.collected_at)}</p>
                </div>
                {t.url && (
                  <a href={t.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:text-blue-800 shrink-0">
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {!submitted && (
        <div className="text-center py-16 text-muted-foreground">
          <Search className="h-10 w-10 mx-auto mb-3 opacity-20" />
          <p className="text-sm">Type at least 2 characters and press Search</p>
        </div>
      )}
    </div>
  );
}

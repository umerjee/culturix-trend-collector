"use client";

import { useState } from "react";
import { Sparkles, Loader2, Wand2, AlertCircle } from "lucide-react";
import type { ClusterSummary, ContentIdea } from "@/lib/types";
import DigestCard from "@/components/DigestCard";

interface Props {
  cluster: ClusterSummary;
  existingIdea: ContentIdea | null;
  existingIdeaIndex: number | null; // position in digest.content_ideas — null if existingIdea is null
  contentId: string;
  clusterIndex: number;
  plan: "free" | "pro";
  connectedPlatforms: string[];
  publishMode: "manual" | "review" | "auto";
}

export default function TrendIdeaCard({
  cluster, existingIdea, existingIdeaIndex, contentId, clusterIndex, plan, connectedPlatforms, publishMode,
}: Props) {
  const [idea, setIdea] = useState<ContentIdea | null>(existingIdea);
  const [ideaIndex, setIdeaIndex] = useState<number | null>(existingIdeaIndex);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    if (generating) return;
    setGenerating(true);
    setError(null);
    try {
      const res = await fetch("/api/generate-idea", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content_id: contentId, cluster_index: clusterIndex }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? `Error ${res.status}`);
        return;
      }
      const { idea_index, ...ideaFields } = data;
      setIdea(ideaFields as ContentIdea);
      setIdeaIndex(idea_index);
    } catch {
      setError("Network error — check your connection");
    } finally {
      setGenerating(false);
    }
  }

  const trendHeader = (
    <div className="flex flex-wrap items-start gap-x-2 gap-y-1 px-1">
      <p className="flex-1 min-w-[10rem] font-semibold text-sm text-gray-900">{cluster.name}</p>
      {cluster.emotional_theme && (
        <span className="shrink-0 inline-flex items-center gap-1 text-xs font-medium rounded-full bg-purple-50 text-purple-600 px-2 py-0.5">
          <Sparkles className="h-3 w-3" />
          {cluster.emotional_theme}
        </span>
      )}
    </div>
  );

  if (idea && ideaIndex !== null) {
    // DigestCard already provides full card chrome (border/padding/shadow) —
    // the trend label sits above it as a plain heading, not another bordered
    // wrapper, so this doesn't render as a card nested inside a card.
    return (
      <div className="space-y-1.5">
        {trendHeader}
        <DigestCard
          idea={idea}
          index={ideaIndex}
          contentId={contentId}
          plan={plan}
          connectedPlatforms={connectedPlatforms}
          publishMode={publishMode}
        />
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-white border border-gray-100 p-4">
      {trendHeader}
      <p className="text-xs text-gray-500 line-clamp-2 mt-1">{cluster.description}</p>
      {cluster.why_it_matters && (
        <p className="text-xs text-gray-400 mt-2 italic line-clamp-2">{cluster.why_it_matters}</p>
      )}

      <div className="mt-3 pt-3 border-t border-gray-50 space-y-2">
        <button
          onClick={generate}
          disabled={generating}
          className="w-full flex items-center justify-center gap-1.5 rounded-lg border border-gray-200 py-2 text-xs font-medium text-gray-500 hover:border-blue-300 hover:text-blue-600 transition-colors disabled:opacity-60"
        >
          {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
          {generating ? "Generating…" : "Generate content ideas"}
        </button>
        {error && (
          <p className="flex items-start gap-1.5 text-xs text-red-500">
            <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

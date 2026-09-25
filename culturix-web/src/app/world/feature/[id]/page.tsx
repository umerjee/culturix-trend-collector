import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, MapPin } from "lucide-react";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";
import FeatureTranscript from "@/components/world/FeatureTranscript";
import RelatedShowcaseStrip from "@/components/world/RelatedShowcaseStrip";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import { CATEGORY_LABELS } from "@/lib/worldTypes";
import type { WorldFeature } from "@/lib/worldTypes";

async function fetchFeature(id: string): Promise<WorldFeature | null> {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/features/${id}`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: { id: string } }) {
  const feature = await fetchFeature(params.id);
  return { title: feature ? `${feature.title || feature.subject_text} — Culturix World` : "Culturix World" };
}

export default async function WorldFeaturePage({ params }: { params: { id: string } }) {
  const feature = await fetchFeature(params.id);
  if (!feature) notFound();

  return (
    <div className="min-h-screen bg-white">
      <MarketingHeader />

      <main className="max-w-2xl mx-auto px-4 sm:px-6 py-14">
        <Link
          href={feature.subject_region ? `/world/region/${feature.subject_region}` : "/world"}
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-purple-600 mb-8"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back
        </Link>

        <div className="rounded-2xl overflow-hidden bg-gray-900 mb-6">
          {feature.final_video_url && (
            <video
              src={feature.final_video_url}
              controls
              playsInline
              preload="metadata"
              poster={feature.thumbnail_url || undefined}
              className="w-full max-h-[70vh] mx-auto"
              // feature.thumbnail_url (the source article's own lead image, see FeatureCard.tsx)
              // is passed as `poster` above when present — the browser shows it natively before
              // playback starts, no seek trick needed. Only Features with no thumbnail_url (no
              // Wikipedia lead image, or ingested before this field existed) fall back to nudging
              // past a moment into the clip to force a real frame decode instead of showing black.
              // Unlike FeatureCard's muted, never-actually-played thumbnail, this IS the real
              // player, so the seek must be undone the moment playback actually starts —
              // otherwise pressing play would silently skip the first second every time.
              onLoadedMetadata={(e) => {
                if (feature.thumbnail_url) return;
                const video = e.currentTarget;
                video.currentTime = Math.min(1.2, Math.max(0, (video.duration || 0) - 0.1));
              }}
              onPlay={(e) => {
                if (feature.thumbnail_url) return;
                const video = e.currentTarget;
                if (video.currentTime < 1.3) video.currentTime = 0;
              }}
            />
          )}
        </div>

        <div className="flex items-center gap-2 mb-3">
          {feature.subject_category && (
            <span className="inline-flex items-center rounded-full bg-purple-50 text-purple-600 text-[11px] font-semibold px-2 py-0.5">
              {CATEGORY_LABELS[feature.subject_category] || feature.subject_category}
            </span>
          )}
          {feature.subject_region && (
            <span className="inline-flex items-center gap-1 text-xs text-gray-400">
              <MapPin className="h-3 w-3" /> {feature.subject_region}
            </span>
          )}
        </div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">{feature.title || feature.subject_text}</h1>
        {feature.hook_line && <p className="text-gray-500 leading-relaxed">{feature.hook_line}</p>}

        <FeatureTranscript featureId={feature.id} initial={feature.transcript || []} />

        <RelatedShowcaseStrip toons={feature.related_toons} />

        {feature.source && (
          <p className="mt-6 text-xs text-gray-400">
            Source:{" "}
            <a href={feature.source.url} target="_blank" rel="noopener noreferrer" className="text-purple-600 hover:underline">
              {feature.source.label}
            </a>
          </p>
        )}
      </main>

      <MarketingFooter />
    </div>
  );
}

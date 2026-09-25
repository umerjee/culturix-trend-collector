"use client";

import Link from "next/link";
import { MapPin } from "lucide-react";
import type { WorldFeature } from "@/lib/worldTypes";
import { CATEGORY_LABELS } from "@/lib/worldTypes";

// This card is rendered from server components (the /world grid, region pages) but must be
// a client component itself: the video thumbnail fix below passes onLoadedMetadata, an event
// handler, as a prop — Next.js does not allow passing functions as props across the server/
// client boundary ("Event handlers cannot be passed to Client Component props"), which broke
// EVERY page rendering this card with a hard 500 the moment that fix shipped. Confirmed live.

// feature.thumbnail_url is the source article's own lead image (a real, topic-
// representative photo — see CuratedItem.thumbnail_url on the backend) and is preferred
// whenever present: an <img> is cheaper to render in a grid than a <video> and, unlike a
// frame grabbed from the generated clip, it actually depicts the subject rather than
// whatever the render happened to open on.
//
// Older Features (ingested before thumbnail_url existed) or ones with no Wikipedia lead
// image fall back to the <video> element's own first frame — but preload="metadata" alone
// often renders that as solid black (confirmed live: most cards on /world showed a black
// box, one didn't). Two likely causes, both sidestepped the same way: some browsers don't
// decode ANY frame under preload="metadata" until playback starts, and generated clips
// commonly open on a fade-in from black regardless. Nudging currentTime forward a moment
// once metadata is available forces a real frame decode without playing the clip or
// fetching the whole file.
const THUMBNAIL_SEEK_SECONDS = 1.2;

export default function FeatureCard({ feature }: { feature: WorldFeature }) {
  return (
    <Link
      href={`/world/feature/${feature.id}`}
      className="group rounded-2xl border border-gray-100 overflow-hidden hover:border-purple-200 transition-colors block"
    >
      <div className="relative aspect-[9/16] bg-gray-900 overflow-hidden">
        {feature.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- external Wikipedia URL, not in next/image's domain allowlist
          <img
            src={feature.thumbnail_url}
            alt={feature.title || feature.subject_text || ""}
            // Real Wikipedia lead images span wildly different content types side by side in
            // one grid — a 19th-century map next to a macro photo next to a scientific ribbon
            // diagram next to a coat of arms — each individually accurate but, unfiltered,
            // reading as visually chaotic together (confirmed live). A slight desaturation
            // plus the purple duotone wash below (multiply-blended, so it unifies tone without
            // flattening detail) gives every card one consistent visual identity regardless of
            // what the source image actually looks like.
            className="w-full h-full object-cover saturate-[0.82] contrast-[1.04]"
          />
        ) : feature.final_video_url && (
          <video
            src={feature.final_video_url}
            muted
            playsInline
            preload="metadata"
            className="w-full h-full object-cover saturate-[0.82] contrast-[1.04]"
            onLoadedMetadata={(e) => {
              const video = e.currentTarget;
              video.currentTime = Math.min(THUMBNAIL_SEEK_SECONDS, Math.max(0, (video.duration || 0) - 0.1));
            }}
          />
        )}
        {(feature.thumbnail_url || feature.final_video_url) && (
          <div
            className="pointer-events-none absolute inset-0 bg-gradient-to-t from-purple-950/70 via-purple-900/15 to-purple-950/25"
            style={{ mixBlendMode: "multiply" }}
            aria-hidden="true"
          />
        )}
      </div>
      <div className="p-4">
        {feature.subject_category && (
          <span className="inline-flex items-center rounded-full bg-purple-50 text-purple-600 text-[11px] font-semibold px-2 py-0.5 mb-2">
            {CATEGORY_LABELS[feature.subject_category] || feature.subject_category}
          </span>
        )}
        <h3 className="font-semibold text-gray-900 text-sm leading-snug group-hover:text-purple-600 transition-colors">
          {feature.title || feature.subject_text}
        </h3>
        {feature.subject_region && (
          <p className="text-xs text-gray-400 mt-1.5 flex items-center gap-1">
            <MapPin className="h-3 w-3" /> {feature.subject_region}
          </p>
        )}
      </div>
    </Link>
  );
}

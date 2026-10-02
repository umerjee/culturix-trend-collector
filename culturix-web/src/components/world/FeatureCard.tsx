"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Globe2, Play } from "lucide-react";
import type { WorldFeature } from "@/lib/worldTypes";
import { CATEGORY_LABELS } from "@/lib/worldTypes";
import { iconForCategory, colorForCategory } from "@/lib/worldCategoryVisuals";
import { countryName, flagEmoji } from "@/lib/worldPlaces";
import { useLocale } from "@/components/i18n/LocaleProvider";

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
//
// In an infinitely scrolling feed that fallback <video> is only mounted while the card is near
// the viewport, so a long feed never accumulates video elements.
const THUMBNAIL_SEEK_SECONDS = 1.2;

function useNearViewport<T extends Element>(enabled: boolean) {
  const ref = useRef<T>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el) return;
    const observer = new IntersectionObserver(([entry]) => setNear(entry.isIntersecting), { rootMargin: "200px" });
    observer.observe(el);
    return () => observer.disconnect();
  }, [enabled]);
  return { ref, near };
}

export default function FeatureCard({ feature }: { feature: WorldFeature }) {
  const { locale, messages } = useLocale();
  const t = messages.world;
  const needsVideoFallback = !feature.thumbnail_url && Boolean(feature.final_video_url);
  const { ref, near } = useNearViewport<HTMLDivElement>(needsVideoFallback);
  const title = feature.title || feature.subject_text || "";
  const place = countryName(feature.subject_region, locale);
  const categoryLabel = feature.subject_category
    ? t.categories[feature.subject_category] || CATEGORY_LABELS[feature.subject_category] || feature.subject_category
    : null;

  return (
    <Link
      href={`/world/feature/${feature.id}`}
      className="group block rounded-2xl border border-gray-100 overflow-hidden bg-white hover:border-purple-200 hover:shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 focus-visible:ring-offset-2"
    >
      <div ref={ref} className="relative aspect-[9/16] bg-gray-900 overflow-hidden">
        {feature.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- external Wikipedia URL, not in next/image's domain allowlist
          <img
            src={feature.thumbnail_url}
            alt=""
            loading="lazy"
            decoding="async"
            // Real Wikipedia lead images span wildly different content types side by side in
            // one grid — a 19th-century map next to a macro photo next to a scientific ribbon
            // diagram next to a coat of arms — each individually accurate but, unfiltered,
            // reading as visually chaotic together (confirmed live). A slight desaturation
            // plus the purple duotone wash below (multiply-blended, so it unifies tone without
            // flattening detail) gives every card one consistent visual identity regardless of
            // what the source image actually looks like.
            className="w-full h-full object-cover saturate-[0.82] contrast-[1.04] transition-transform duration-300 group-hover:scale-[1.03] motion-reduce:transition-none motion-reduce:group-hover:scale-100"
          />
        ) : needsVideoFallback && near && (
          <video
            src={feature.final_video_url!}
            muted
            playsInline
            preload="metadata"
            aria-hidden="true"
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
        {categoryLabel && (() => {
          const Icon = iconForCategory(feature.subject_category);
          const color = colorForCategory(feature.subject_category);
          return (
            <span
              className="absolute top-2 left-2 inline-flex items-center gap-1 rounded-full bg-white/95 text-[11px] font-semibold px-2 py-0.5 shadow-sm"
              style={{ color }}
            >
              <Icon className="h-3 w-3" aria-hidden="true" /> {categoryLabel}
            </span>
          );
        })()}
        <span
          className="absolute inset-0 flex items-center justify-center"
          aria-hidden="true"
        >
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-black/45 text-white backdrop-blur-sm ring-1 ring-white/40 transition-transform group-hover:scale-110 motion-reduce:transition-none">
            <Play className="h-5 w-5 translate-x-[1px]" fill="currentColor" />
          </span>
        </span>
      </div>
      <div className="p-3 sm:p-4">
        <h3 className="font-semibold text-gray-900 text-sm leading-snug line-clamp-2 group-hover:text-purple-600 transition-colors">
          {title}
        </h3>
        {feature.hook_line && (
          <p className="mt-1 text-xs leading-snug text-gray-500 line-clamp-2">{feature.hook_line}</p>
        )}
        <p className="text-xs text-gray-500 mt-2 flex items-center gap-1.5 min-w-0">
          {place ? (
            <>
              <span aria-hidden="true">{flagEmoji(feature.subject_region)}</span>
              <span className="truncate">{place}</span>
            </>
          ) : (
            <>
              <Globe2 className="h-3 w-3 shrink-0" aria-hidden="true" />
              <span className="truncate">{t.worldwide}</span>
            </>
          )}
        </p>
      </div>
    </Link>
  );
}

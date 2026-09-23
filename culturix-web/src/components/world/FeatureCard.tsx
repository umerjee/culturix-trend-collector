import Link from "next/link";
import { MapPin } from "lucide-react";
import type { WorldFeature } from "@/lib/worldTypes";
import { CATEGORY_LABELS } from "@/lib/worldTypes";

// There is no generated poster image anywhere in the render pipeline, so this relies on
// the <video> element's own first frame — but preload="metadata" alone often renders that
// as solid black (confirmed live: most cards on /world showed a black box, one didn't).
// Two likely causes, both sidestepped the same way: some browsers don't decode ANY frame
// under preload="metadata" until playback starts, and generated clips commonly open on a
// fade-in from black regardless. Nudging currentTime forward a moment once metadata is
// available forces a real frame decode without playing the clip or fetching the whole file.
const THUMBNAIL_SEEK_SECONDS = 1.2;

export default function FeatureCard({ feature }: { feature: WorldFeature }) {
  return (
    <Link
      href={`/world/feature/${feature.id}`}
      className="group rounded-2xl border border-gray-100 overflow-hidden hover:border-purple-200 transition-colors block"
    >
      <div className="aspect-[9/16] bg-gray-900">
        {feature.final_video_url && (
          <video
            src={feature.final_video_url}
            muted
            playsInline
            preload="metadata"
            className="w-full h-full object-cover"
            onLoadedMetadata={(e) => {
              const video = e.currentTarget;
              video.currentTime = Math.min(THUMBNAIL_SEEK_SECONDS, Math.max(0, (video.duration || 0) - 0.1));
            }}
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

import type { WorldFeature } from "@/lib/worldTypes";

// CultureToons clips explicitly marked public (Toon.public_showcase) whose character's
// home_region matches this World Feature's region — see app/routers/world.py's
// _related_showcase_toons. Deliberately never auto-populated: every clip here was chosen
// by a curator, not inferred.
const THUMBNAIL_SEEK_SECONDS = 1.2;

export default function RelatedShowcaseStrip({ toons }: { toons: WorldFeature["related_toons"] }) {
  if (!toons || toons.length === 0) return null;

  return (
    <section className="mt-10 border-t border-gray-100 pt-8">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500 mb-4">
        More from this region
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        {toons.map((toon) => (
          <div key={toon.id} className="rounded-2xl border border-gray-100 overflow-hidden">
            <div className="aspect-[9/16] bg-gray-900">
              <video
                src={toon.final_video_url}
                muted
                playsInline
                preload="metadata"
                className="w-full h-full object-cover"
                // No thumbnail image exists for CultureToons clips (unlike World Features'
                // Wikipedia-sourced thumbnail_url) — same seek-forward fallback FeatureCard.tsx
                // uses: nudges past the opening fade-to-black to force a real frame decode.
                onLoadedMetadata={(e) => {
                  const video = e.currentTarget;
                  video.currentTime = Math.min(THUMBNAIL_SEEK_SECONDS, Math.max(0, (video.duration || 0) - 0.1));
                }}
              />
            </div>
            <div className="px-3 py-2.5">
              <p className="text-xs font-medium text-gray-900 truncate">{toon.title || "Untitled"}</p>
              {toon.character_name && <p className="text-[11px] text-gray-400">{toon.character_name}</p>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

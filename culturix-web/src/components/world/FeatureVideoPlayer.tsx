"use client";

// Confirmed live 2026-10-02 (real Vercel function logs): world/feature/[id]/page.tsx is a
// server component rendering this <video> directly, with onLoadedMetadata/onPlay as inline
// arrow functions -- "Event handlers cannot be passed to Client Component props," a hard 500 on
// every single visit to a feature page. FeatureCard.tsx's own docstring already describes this
// exact error class from an earlier fix (its own video thumbnail), but this second, separate
// <video> element in the feature detail page was never moved into a Client Component the same
// way. A function can only be passed to a DOM element from within a "use client" boundary.
export default function FeatureVideoPlayer({
  src, thumbnailUrl, autoPlay = false, onEnded, label,
}: {
  src: string; thumbnailUrl?: string | null;
  // Always muted: autoplay never starts with sound. The viewer unmutes with the controls.
  autoPlay?: boolean;
  onEnded?: () => void;
  label?: string;
}) {
  return (
    <video
      src={src}
      controls
      playsInline
      preload="metadata"
      autoPlay={autoPlay}
      muted={autoPlay}
      aria-label={label}
      poster={thumbnailUrl || undefined}
      className="w-full h-full object-cover bg-black"
      onEnded={onEnded}
      // thumbnailUrl (the source article's own lead image, see FeatureCard.tsx) is passed as
      // `poster` above when present — the browser shows it natively before playback starts, no
      // seek trick needed. Only Features with no thumbnailUrl (no Wikipedia lead image, or
      // ingested before this field existed) fall back to nudging past a moment into the clip to
      // force a real frame decode instead of showing black. Unlike FeatureCard's muted,
      // never-actually-played thumbnail, this IS the real player, so the seek must be undone the
      // moment playback actually starts — otherwise pressing play would silently skip the first
      // second every time.
      onLoadedMetadata={(e) => {
        if (thumbnailUrl || autoPlay) return;
        const video = e.currentTarget;
        video.currentTime = Math.min(1.2, Math.max(0, (video.duration || 0) - 0.1));
      }}
      onPlay={(e) => {
        if (thumbnailUrl || autoPlay) return;
        const video = e.currentTarget;
        if (video.currentTime < 1.3) video.currentTime = 0;
      }}
    />
  );
}

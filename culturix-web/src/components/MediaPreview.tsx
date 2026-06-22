"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, AlertCircle } from "lucide-react";
import type { GeneratedMedia } from "@/lib/types";

interface Props {
  contentId: string;
  ideaIndex: number;
  mediaType: "voiceover" | "music" | "video";
  onDone?: () => void;
}

export default function MediaPreview({ contentId, ideaIndex, mediaType, onDone }: Props) {
  const [media, setMedia] = useState<GeneratedMedia | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let stopped = false;

    async function poll() {
      try {
        const res = await fetch(
          `/api/generate-media/${contentId}?idea_index=${ideaIndex}`
        );
        if (!res.ok) return;
        const rows: GeneratedMedia[] = await res.json();
        const row = rows.find(r => r.media_type === mediaType);
        if (!row) return;
        setMedia(row);
        if (row.status === "done" || row.status === "failed") {
          if (intervalRef.current) clearInterval(intervalRef.current);
          if (row.status === "done") onDone?.();
        }
      } catch {}
    }

    poll();
    intervalRef.current = setInterval(() => {
      if (!stopped) poll();
    }, 5000);

    return () => {
      stopped = true;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [contentId, ideaIndex, mediaType]);

  if (!media) return (
    <div className="flex items-center gap-2 text-xs text-gray-400 mt-1">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      Queued…
    </div>
  );

  if (media.status === "pending" || media.status === "processing") {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-400 mt-1">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {media.status === "pending" ? "Queued…" : "Generating…"}
      </div>
    );
  }

  if (media.status === "failed") {
    return (
      <div className="flex items-start gap-1.5 text-xs text-red-500 mt-1">
        <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        <span className="line-clamp-2">{media.error ?? "Generation failed"}</span>
      </div>
    );
  }

  if (media.status === "done" && media.asset_url) {
    const isVideo = media.media_type === "video";
    const duration = media.duration_seconds
      ? `${Math.round(media.duration_seconds)}s`
      : "";
    return (
      <div className="mt-2 space-y-1">
        {isVideo ? (
          <video
            src={media.asset_url}
            controls
            playsInline
            className="w-full rounded-lg max-h-48 bg-black"
          />
        ) : (
          <audio src={media.asset_url} controls className="w-full h-8" />
        )}
        {duration && (
          <p className="text-xs text-gray-400">{duration}</p>
        )}
      </div>
    );
  }

  return null;
}

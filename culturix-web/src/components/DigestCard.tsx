"use client";

import { useState, type ReactNode } from "react";
import { Music, Target, Megaphone, Copy, Check, Film, Mic, Video, Loader2 } from "lucide-react";
import type { ContentIdea } from "@/lib/types";
import MediaPreview from "@/components/MediaPreview";

const PLATFORM_COLORS: Record<string, string> = {
  TikTok: "bg-pink-100 text-pink-700",
  YouTube: "bg-red-100 text-red-700",
  Instagram: "bg-purple-100 text-purple-700",
  Xiaohongshu: "bg-rose-100 text-rose-700",
  "X/Twitter": "bg-sky-100 text-sky-700",
  Reddit: "bg-orange-100 text-orange-700",
};

interface Props {
  idea: ContentIdea;
  index: number;
  contentId: string;
  plan: "free" | "pro";
}

type MediaType = "voiceover" | "music" | "video";

function CopyBtn({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).catch(() => {});
    setDone(true);
    setTimeout(() => setDone(false), 2000);
  };
  return (
    <button
      onClick={copy}
      title={`Copy ${label}`}
      className="shrink-0 p-1 rounded text-gray-300 hover:text-gray-500 hover:bg-gray-100 transition-colors"
    >
      {done ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

export default function DigestCard({ idea, index, contentId, plan }: Props) {
  const [postCopied, setPostCopied] = useState(false);
  const [activeMedia, setActiveMedia] = useState<Set<MediaType>>(new Set());
  const [generating, setGenerating] = useState<Set<MediaType>>(new Set());
  const [mediaError, setMediaError] = useState<string | null>(null);

  const platformColor = PLATFORM_COLORS[idea.platform] ?? "bg-gray-100 text-gray-700";
  const isPro = plan === "pro";

  const fullPost = [idea.hook, "", idea.caption, "", idea.cta ? `👉 ${idea.cta}` : ""]
    .join("\n").trim();

  const copyPost = () => {
    navigator.clipboard.writeText(fullPost).catch(() => {});
    setPostCopied(true);
    setTimeout(() => setPostCopied(false), 2000);
  };

  async function generateMedia(mt: MediaType) {
    if (!isPro || generating.has(mt)) return;
    setMediaError(null);
    setGenerating(prev => new Set(prev).add(mt));

    const prompts: Record<string, string> = {
      voiceover: idea.hook,
      music: idea.music_mood || "Upbeat trending pop",
      video: idea.video_prompt || idea.hook,
    };

    try {
      const res = await fetch("/api/generate-media", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content_id: contentId,
          idea_index: index,
          media_types: [mt],
          prompts,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setMediaError(err.detail ?? `Error ${res.status}`);
        setGenerating(prev => { const s = new Set(prev); s.delete(mt); return s; });
        return;
      }
      setActiveMedia(prev => new Set(prev).add(mt));
    } catch (e) {
      setMediaError("Network error — check your connection");
    }
    setGenerating(prev => { const s = new Set(prev); s.delete(mt); return s; });
  }

  const MEDIA_BTNS: { type: MediaType; label: string; icon: ReactNode }[] = [
    { type: "voiceover", label: "Voiceover", icon: <Mic className="h-3.5 w-3.5" /> },
    { type: "music",     label: "Music",     icon: <Music className="h-3.5 w-3.5" /> },
    { type: "video",     label: "Video",     icon: <Video className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-5 flex flex-col gap-4 hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-bold text-gray-300">#{String(index + 1).padStart(2, "0")}</span>
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          {idea.format && (
            <span className="inline-flex items-center gap-1 text-xs font-medium rounded-full bg-gray-100 text-gray-500 px-2.5 py-1">
              <Film className="h-3 w-3" />
              {idea.format}
            </span>
          )}
          <span className={`text-xs font-semibold rounded-full px-2.5 py-1 ${platformColor}`}>
            {idea.platform}
          </span>
        </div>
      </div>

      {/* Hook */}
      <div className="flex items-start justify-between gap-2">
        <p className="text-base font-bold text-gray-900 leading-snug flex-1">{idea.hook}</p>
        <CopyBtn text={idea.hook} label="hook" />
      </div>

      {/* Caption */}
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-gray-600 leading-relaxed flex-1 whitespace-pre-line">{idea.caption}</p>
        <CopyBtn text={idea.caption} label="caption" />
      </div>

      {/* Meta */}
      <div className="space-y-2 border-t border-gray-50 pt-3">
        <div className="flex items-start gap-2">
          <Megaphone className="h-3.5 w-3.5 text-blue-500 mt-0.5 shrink-0" />
          <p className="text-xs text-gray-600 flex-1">{idea.cta}</p>
          <CopyBtn text={idea.cta} label="CTA" />
        </div>
        {idea.music_mood && (
          <div className="flex items-center gap-2">
            <Music className="h-3.5 w-3.5 text-purple-400 shrink-0" />
            <p className="text-xs text-gray-500">{idea.music_mood}</p>
          </div>
        )}
        {idea.trend_connection && (
          <div className="flex items-start gap-2">
            <Target className="h-3.5 w-3.5 text-green-500 mt-0.5 shrink-0" />
            <p className="text-xs text-gray-500">{idea.trend_connection}</p>
          </div>
        )}
      </div>

      {/* Media generation buttons */}
      <div className="border-t border-gray-50 pt-3 space-y-2">
        <div className="flex gap-2">
          {MEDIA_BTNS.map(({ type, label, icon }) => {
            const isActive = activeMedia.has(type);
            const isBusy = generating.has(type);
            return (
              <button
                key={type}
                onClick={() => generateMedia(type)}
                disabled={!isPro || isBusy}
                title={!isPro ? "Upgrade to Pro to generate media" : `Generate ${label}`}
                className={`flex-1 flex items-center justify-center gap-1.5 rounded-lg border py-1.5 text-xs font-medium transition-all
                  ${isActive ? "border-blue-200 bg-blue-50 text-blue-600" : "border-gray-200 text-gray-500"}
                  ${!isPro ? "opacity-40 cursor-not-allowed" : "hover:border-blue-300 hover:text-blue-600 cursor-pointer"}
                `}
              >
                {isBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : icon}
                {isBusy ? "Generating…" : label}
              </button>
            );
          })}
        </div>
        {!isPro && (
          <p className="text-xs text-center text-gray-400">
            <span className="font-medium text-indigo-500">Pro</span> — unlock voiceover, music & video generation
          </p>
        )}
        {mediaError && (
          <p className="text-xs text-red-500 text-center">{mediaError}</p>
        )}
        {/* Media preview players (one per active type) */}
        {Array.from(activeMedia).map(mt => (
          <MediaPreview
            key={mt}
            contentId={contentId}
            ideaIndex={index}
            mediaType={mt}
          />
        ))}
      </div>

      {/* Copy full post */}
      <button
        onClick={copyPost}
        className={`mt-auto w-full flex items-center justify-center gap-2 rounded-xl border py-2.5 text-xs font-semibold transition-all ${
          postCopied
            ? "border-green-200 bg-green-50 text-green-600"
            : "border-gray-200 text-gray-500 hover:border-blue-300 hover:text-blue-600 hover:bg-blue-50"
        }`}
      >
        {postCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        {postCopied ? "Copied!" : "Copy full post"}
      </button>
    </div>
  );
}

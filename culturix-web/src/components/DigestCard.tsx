"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Music, Target, Megaphone, Copy, Check, Film, Mic, Video, Image as ImageIcon, Loader2, Clock, Zap, ChevronDown, ChevronUp, Send, Link2 } from "lucide-react";
import type { ContentIdea, ContentPost } from "@/lib/types";
import MediaPreview from "@/components/MediaPreview";
import PostPerformance from "@/components/PostPerformance";

const PLATFORM_COLORS: Record<string, string> = {
  TikTok: "bg-pink-100 text-pink-700",
  YouTube: "bg-red-100 text-red-700",
  Instagram: "bg-purple-100 text-purple-700",
  Xiaohongshu: "bg-rose-100 text-rose-700",
  "X/Twitter": "bg-sky-100 text-sky-700",
  Reddit: "bg-orange-100 text-orange-700",
};

const VIRAL_COLORS: [string, string][] = [
  ["hot take",      "bg-orange-50 text-orange-600 border-orange-200"],
  ["myth",          "bg-yellow-50 text-yellow-700 border-yellow-200"],
  ["pov",           "bg-indigo-50 text-indigo-600 border-indigo-200"],
  ["transformation","bg-emerald-50 text-emerald-600 border-emerald-200"],
  ["duet",          "bg-pink-50 text-pink-600 border-pink-200"],
  ["challenge",     "bg-blue-50 text-blue-600 border-blue-200"],
  ["reaction",      "bg-purple-50 text-purple-600 border-purple-200"],
  ["tutorial",      "bg-teal-50 text-teal-600 border-teal-200"],
];

function viralAngleClass(angle: string): string {
  const lower = angle.toLowerCase();
  const match = VIRAL_COLORS.find(([key]) => lower.includes(key));
  return match ? match[1] : "bg-gray-50 text-gray-600 border-gray-200";
}

const STATUS_BADGE: Record<string, { emoji: string; label: string; className: string }> = {
  live: { emoji: "\u{1F7E2}", label: "Live", className: "bg-green-50 text-green-700" },
  aging: { emoji: "\u{1F7E1}", label: "Aging", className: "bg-yellow-50 text-yellow-700" },
  stale: { emoji: "\u{1F534}", label: "Stale", className: "bg-red-50 text-red-600" },
  retired: { emoji: "\u{1F534}", label: "Retired", className: "bg-red-50 text-red-600" },
};

interface Props {
  idea: ContentIdea;
  index: number;
  contentId: string;
  plan: "free" | "pro";
  connectedPlatforms: string[]; // lowercase platform keys with an active connected account, e.g. ["youtube"]
  publishMode: "manual" | "review" | "auto";
}

// idea.platform (LLM-suggested display value) -> internal provider key —
// only platforms with a real publish()/fetch_post_metrics() implementation
// belong here, matching app/scheduler.py's _AUTO_PUBLISH_PLATFORMS.
const PUBLISHABLE_PLATFORMS: Record<string, string> = {
  YouTube: "youtube", TikTok: "tiktok", Instagram: "instagram", "X/Twitter": "twitter",
};

type MediaType = "voiceover" | "music" | "video" | "image";

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

export default function DigestCard({ idea, index, contentId, plan, connectedPlatforms, publishMode }: Props) {
  const [postCopied, setPostCopied] = useState(false);
  const [activeMedia, setActiveMedia] = useState<Set<MediaType>>(new Set());
  const [generating, setGenerating] = useState<Set<MediaType>>(new Set());
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [showVideoPrompt, setShowVideoPrompt] = useState(false);

  const [existingPost, setExistingPost] = useState<ContentPost | null>(null);
  const [videoReady, setVideoReady] = useState(false);
  const [showPostForm, setShowPostForm] = useState(false);
  const [postUrl, setPostUrl] = useState("");
  const [postSubmitting, setPostSubmitting] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);

  const platformColor = PLATFORM_COLORS[idea.platform] ?? "bg-gray-100 text-gray-700";
  const isPro = plan === "pro";
  const hashtags = idea.hashtag_strategy?.split(/\s+/).filter(h => h.startsWith("#")) ?? [];
  const backendPlatform = PUBLISHABLE_PLATFORMS[idea.platform];
  // "Mark as posted" tracking is available regardless of publish_mode — even
  // Review/Auto users may occasionally post manually and still want tracking.
  const canTrack = !!backendPlatform && connectedPlatforms.includes(backendPlatform);
  // The one-click "Publish" button is hidden for "manual" profiles — that
  // mode's whole premise (per the Settings page copy) is "Culturix never
  // posts for you," so showing an auto-publish button there would contradict it.
  const canOneClickPublish = canTrack && publishMode !== "manual";
  const canPublishOrTrack = canTrack;

  // One-time check on mount — whether this idea already has a tracked/published
  // post (persists across reloads, unlike activeMedia's session-only state) and
  // whether its video has already finished generating (gates the Publish button).
  useEffect(() => {
    if (!canPublishOrTrack) return;
    let cancelled = false;
    (async () => {
      try {
        const [postsRes, mediaRes] = await Promise.all([
          fetch(`/api/content-posts/${contentId}?idea_index=${index}`),
          fetch(`/api/generate-media/${contentId}?idea_index=${index}`),
        ]);
        if (!cancelled && postsRes.ok) {
          const rows: ContentPost[] = await postsRes.json();
          if (rows[0]) setExistingPost(rows[0]);
        }
        if (!cancelled && mediaRes.ok) {
          const rows: { media_type: string; status: string }[] = await mediaRes.json();
          if (rows.some(r => r.media_type === "video" && r.status === "done")) setVideoReady(true);
        }
      } catch {}
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fullPost = [
    idea.hook, "",
    idea.caption, "",
    idea.cta ? `👉 ${idea.cta}` : "",
    "",
    hashtags.join(" "),
  ].join("\n").trim();

  const copyPost = () => {
    navigator.clipboard.writeText(fullPost).catch(() => {});
    setPostCopied(true);
    setTimeout(() => setPostCopied(false), 2000);
  };

  async function generateMedia(mt: MediaType) {
    if (!isPro || generating.has(mt)) return;
    setMediaError(null);
    setGenerating(prev => new Set(prev).add(mt));

    try {
      const res = await fetch("/api/generate-media", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content_id: contentId,
          idea_index: index,
          media_types: [mt],
          prompts: {
            voiceover: idea.hook,
            music: idea.music_mood || "Upbeat trending pop",
            video: idea.video_prompt || idea.hook,
            image: idea.video_prompt || idea.hook,
          },
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setMediaError(err.detail ?? `Error ${res.status}`);
        setGenerating(prev => { const s = new Set(prev); s.delete(mt); return s; });
        return;
      }
      setActiveMedia(prev => new Set(prev).add(mt));
    } catch {
      setMediaError("Network error — check your connection");
    }
    setGenerating(prev => { const s = new Set(prev); s.delete(mt); return s; });
  }

  async function markAsPosted() {
    if (!postUrl.trim() || postSubmitting) return;
    setPostSubmitting(true);
    setPostError(null);
    try {
      const res = await fetch("/api/content-posts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content_id: contentId, idea_index: index,
          platform: backendPlatform, post_url: postUrl.trim(),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setPostError(err.detail ?? `Error ${res.status}`);
        return;
      }
      const data = await res.json();
      setExistingPost({ id: data.content_post_id, status: "pending" } as ContentPost);
      setShowPostForm(false);
    } catch {
      setPostError("Network error — check your connection");
    } finally {
      setPostSubmitting(false);
    }
  }

  async function publishNow() {
    if (postSubmitting) return;
    if (!videoReady) { generateMedia("video"); return; }
    setPostSubmitting(true);
    setPostError(null);
    try {
      const res = await fetch("/api/content-posts/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content_id: contentId, idea_index: index, platform: backendPlatform }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setPostError(err.detail ?? `Error ${res.status}`);
        return;
      }
      const data = await res.json();
      setExistingPost({ id: data.content_post_id, status: "pending" } as ContentPost);
    } catch {
      setPostError("Network error — check your connection");
    } finally {
      setPostSubmitting(false);
    }
  }

  const ALL_MEDIA_BTNS: { type: MediaType; label: string; icon: ReactNode }[] = [
    { type: "image",     label: "Image",     icon: <ImageIcon className="h-3.5 w-3.5" /> },
    { type: "voiceover", label: "Voiceover", icon: <Mic className="h-3.5 w-3.5" /> },
    { type: "music",     label: "Music",     icon: <Music className="h-3.5 w-3.5" /> },
    { type: "video",     label: "Video",     icon: <Video className="h-3.5 w-3.5" /> },
  ];
  // idea.medium is absent on ideas generated before the preferred-formats
  // feature — fail open to "show everything" (video's full set) rather than
  // "show nothing" for that old data. Photo/text ideas only ever get an Image
  // button — there's no voiceover/music/video to speak over or score for them.
  const MEDIA_BTNS = !idea.medium || idea.medium === "video"
    ? ALL_MEDIA_BTNS
    : ALL_MEDIA_BTNS.filter(b => b.type === "image");

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-5 flex flex-col gap-4 hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-xs font-bold text-gray-300">#{String(index + 1).padStart(2, "0")}</span>
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          {idea.status && (
            <span
              title={idea.relevance_score != null ? `Relevance: ${idea.relevance_score}` : undefined}
              className={`inline-flex items-center gap-1 text-xs font-medium rounded-full px-2.5 py-1 ${STATUS_BADGE[idea.status].className}`}
            >
              {STATUS_BADGE[idea.status].emoji} {STATUS_BADGE[idea.status].label}
            </span>
          )}
          {idea.viral_angle && (
            <span className={`inline-flex items-center gap-1 text-xs font-medium rounded-full border px-2.5 py-1 ${viralAngleClass(idea.viral_angle)}`}>
              <Zap className="h-3 w-3" />
              {idea.viral_angle}
            </span>
          )}
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

      {/* Hashtag chips */}
      {hashtags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {hashtags.map((tag, i) => (
            <button
              key={i}
              onClick={() => navigator.clipboard.writeText(tag).catch(() => {})}
              title={`Copy ${tag}`}
              className="inline-flex items-center text-xs rounded-full bg-indigo-50 text-indigo-600 hover:bg-indigo-100 px-2 py-0.5 transition-colors"
            >
              {tag}
            </button>
          ))}
        </div>
      )}

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
        {idea.posting_time && (
          <div className="flex items-start gap-2">
            <Clock className="h-3.5 w-3.5 text-amber-500 mt-0.5 shrink-0" />
            <p className="text-xs text-gray-500">{idea.posting_time}</p>
          </div>
        )}
      </div>

      {/* Video brief (collapsible) */}
      {idea.video_prompt && (
        <div className="border-t border-gray-50 pt-3">
          <button
            onClick={() => setShowVideoPrompt(v => !v)}
            className="flex items-center gap-1.5 text-xs font-medium text-gray-400 hover:text-gray-600 transition-colors"
          >
            <Film className="h-3.5 w-3.5" />
            Video brief
            {showVideoPrompt ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
          {showVideoPrompt && (
            <div className="mt-2 flex items-start gap-2">
              <p className="text-xs text-gray-500 italic flex-1 leading-relaxed">{idea.video_prompt}</p>
              <CopyBtn text={idea.video_prompt} label="video prompt" />
            </div>
          )}
        </div>
      )}

      {/* Media generation */}
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
        {Array.from(activeMedia).map(mt => (
          <MediaPreview
            key={mt} contentId={contentId} ideaIndex={index} mediaType={mt}
            onDone={mt === "video" ? () => setVideoReady(true) : undefined}
          />
        ))}
      </div>

      {/* Publish / track */}
      {canPublishOrTrack && (
        <div className="border-t border-gray-50 pt-3 space-y-2">
          {existingPost ? (
            <PostPerformance contentId={contentId} ideaIndex={index} />
          ) : (
            <>
              <div className="flex gap-2">
                {canOneClickPublish && (
                  <button
                    onClick={publishNow}
                    disabled={!isPro || postSubmitting}
                    title={!isPro ? "Upgrade to Pro to publish" : videoReady ? "Publish now" : "Generate a video first, then publish"}
                    className={`flex-1 flex items-center justify-center gap-1.5 rounded-lg border py-1.5 text-xs font-medium transition-all border-gray-200 text-gray-500
                      ${!isPro ? "opacity-40 cursor-not-allowed" : "hover:border-blue-300 hover:text-blue-600 cursor-pointer"}`}
                  >
                    {postSubmitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                    {videoReady ? "Publish" : "Generate video to publish"}
                  </button>
                )}
                <button
                  onClick={() => setShowPostForm(v => !v)}
                  disabled={!isPro}
                  title={!isPro ? "Upgrade to Pro to track posts" : "Mark as posted"}
                  className={`flex-1 flex items-center justify-center gap-1.5 rounded-lg border py-1.5 text-xs font-medium transition-all border-gray-200 text-gray-500
                    ${!isPro ? "opacity-40 cursor-not-allowed" : "hover:border-blue-300 hover:text-blue-600 cursor-pointer"}`}
                >
                  <Link2 className="h-3.5 w-3.5" />
                  Mark as posted
                </button>
              </div>
              {showPostForm && (
                <div className="flex gap-2">
                  <input
                    type="url"
                    value={postUrl}
                    onChange={e => setPostUrl(e.target.value)}
                    placeholder={`Paste the ${idea.platform} link…`}
                    className="flex-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs focus:border-blue-500 outline-none"
                  />
                  <button
                    onClick={markAsPosted}
                    disabled={postSubmitting || !postUrl.trim()}
                    className="rounded-lg bg-blue-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-blue-700 disabled:opacity-50"
                  >
                    {postSubmitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Track"}
                  </button>
                </div>
              )}
              {postError && <p className="text-xs text-red-500 text-center">{postError}</p>}
            </>
          )}
        </div>
      )}

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

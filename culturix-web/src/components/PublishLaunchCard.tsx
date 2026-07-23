"use client";

import { useState } from "react";
import { Download, Copy, Check, ExternalLink, Loader2 } from "lucide-react";
import { LAUNCH_DISCLAIMER } from "@/content/publishingCopy";

interface StageInfo {
  content_post_id: string;
  video_url: string | null;
  caption_text: string | null;
  target_platform: string;
  status: string;
  post_url: string | null;
}

const APP_SCHEMES: Record<string, string> = {
  tiktok: "tiktok://",
  instagram: "instagram://camera",
  youtube: "vnd.youtube://upload",
  twitter: "twitter://post",
};

const WEB_FALLBACKS: Record<string, string> = {
  tiktok: "https://www.tiktok.com/upload",
  instagram: "https://instagram.com",
  youtube: "https://m.youtube.com/upload",
  twitter: "https://twitter.com/intent/tweet",
};

const PLATFORM_LABELS: Record<string, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube: "YouTube",
  twitter: "X/Twitter",
};

export default function PublishLaunchCard({ stage }: { stage: StageInfo }) {
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [postUrl, setPostUrl] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [confirmed, setConfirmed] = useState(stage.status === "tracked" || stage.status === "pending" || stage.status === "fetching");

  const platform = stage.target_platform.toLowerCase();
  const platformLabel = PLATFORM_LABELS[platform] || stage.target_platform;

  async function saveVideo() {
    if (!stage.video_url) return;
    setSaving(true);
    setSaveError(null);
    try {
      const res = await fetch(stage.video_url);
      const blob = await res.blob();
      const file = new File([blob], "culturix-video.mp4", { type: blob.type || "video/mp4" });

      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], text: stage.caption_text || undefined });
      } else {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "culturix-video.mp4";
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch {
      setSaveError("Couldn't save the video automatically — try opening it directly.");
    } finally {
      setSaving(false);
    }
  }

  async function copyCaption() {
    if (!stage.caption_text) return;
    await navigator.clipboard.writeText(stage.caption_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function openApp() {
    const scheme = APP_SCHEMES[platform];
    const fallback = WEB_FALLBACKS[platform];
    if (!scheme) return;
    window.location.href = scheme;
    setTimeout(() => {
      if (!document.hidden && fallback) window.location.href = fallback;
    }, 1500);
  }

  async function confirmPosted(e: React.FormEvent) {
    e.preventDefault();
    if (!postUrl.trim() || confirming) return;
    setConfirming(true);
    try {
      const res = await fetch(`/api/content-posts/${stage.content_post_id}/confirm-posted`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ post_url: postUrl.trim() }),
      });
      if (res.ok) setConfirmed(true);
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6 space-y-5 shadow-sm">
      <div>
        <h1 className="text-lg font-semibold text-gray-900">Ready to launch on {platformLabel}</h1>
        <p className="text-sm text-gray-500 mt-1">
          Three quick taps: save the video, copy the caption, open {platformLabel} — then paste and post it yourself.
        </p>
      </div>

      <div className="space-y-2.5">
        <button
          onClick={saveVideo}
          disabled={saving || !stage.video_url}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-gray-900 text-white py-3 text-sm font-medium disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          Save video
        </button>
        {saveError && <p className="text-xs text-red-500">{saveError}</p>}

        <button
          onClick={copyCaption}
          disabled={!stage.caption_text}
          className="w-full flex items-center justify-center gap-2 rounded-xl border border-gray-200 py-3 text-sm font-medium text-gray-700 disabled:opacity-50"
        >
          {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
          {copied ? "Copied!" : "Copy caption"}
        </button>

        <button
          onClick={openApp}
          className="w-full flex items-center justify-center gap-2 rounded-xl border border-gray-200 py-3 text-sm font-medium text-gray-700"
        >
          <ExternalLink className="h-4 w-4" />
          Open {platformLabel}
        </button>
      </div>

      {stage.caption_text && (
        <div className="rounded-xl bg-gray-50 p-3 text-xs text-gray-600 whitespace-pre-wrap max-h-40 overflow-y-auto">
          {stage.caption_text}
        </div>
      )}

      <p className="text-xs text-gray-400">Heads up: {LAUNCH_DISCLAIMER}</p>

      <div className="border-t border-gray-100 pt-4">
        {confirmed ? (
          <p className="text-sm text-green-700">Thanks — we&apos;re tracking this post&apos;s performance now.</p>
        ) : (
          <form onSubmit={confirmPosted} className="space-y-2">
            <label className="text-xs font-medium text-gray-500">Posted it? Paste the link so we can track it.</label>
            <div className="flex gap-2">
              <input
                type="url"
                value={postUrl}
                onChange={(e) => setPostUrl(e.target.value)}
                placeholder={`https://${platform}.com/...`}
                className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={confirming || !postUrl.trim()}
                className="rounded-lg bg-gray-900 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
              >
                {confirming ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

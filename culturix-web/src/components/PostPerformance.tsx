"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, AlertCircle, Eye, Heart, MessageCircle, ExternalLink, RefreshCw, Bell } from "lucide-react";
import type { ContentPost } from "@/lib/types";

interface Props {
  contentId: string;
  ideaIndex: number;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function PostPerformance({ contentId, ideaIndex }: Props) {
  const [post, setPost] = useState<ContentPost | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let stopped = false;

    async function poll() {
      try {
        const res = await fetch(`/api/content-posts/${contentId}?idea_index=${ideaIndex}`);
        if (!res.ok) return;
        const rows: ContentPost[] = await res.json();
        const row = rows[0]; // most recent, backend orders created_at desc
        if (!row || stopped) return;
        setPost(row);
        if (["tracked", "failed", "needs_reconnect", "staged"].includes(row.status) && intervalRef.current) {
          clearInterval(intervalRef.current);
        }
      } catch {}
    }

    poll();
    intervalRef.current = setInterval(() => { if (!stopped) poll(); }, 5000);

    return () => {
      stopped = true;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [contentId, ideaIndex]);

  async function refresh() {
    if (!post || refreshing) return;
    setRefreshing(true);
    try {
      await fetch("/api/content-posts/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content_post_id: post.id }),
      });
      intervalRef.current = setInterval(async () => {
        const res = await fetch(`/api/content-posts/${contentId}?idea_index=${ideaIndex}`);
        if (res.ok) {
          const rows: ContentPost[] = await res.json();
          if (rows[0]) setPost(rows[0]);
        }
      }, 3000);
    } finally {
      setTimeout(() => setRefreshing(false), 3000);
    }
  }

  if (!post) return null;

  if (post.status === "pending" || post.status === "fetching") {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-400 mt-1">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {post.created_via === "published" ? "Publishing…" : "Fetching stats…"}
      </div>
    );
  }

  if (post.status === "staged") {
    return (
      <div className="mt-2 rounded-lg bg-blue-50 border border-blue-100 px-3 py-2 space-y-1.5 text-xs text-blue-700">
        <div className="flex items-center gap-1.5">
          <Bell className="h-3.5 w-3.5 shrink-0" />
          <span>
            {post.notification_status === "failed"
              ? "Ready to launch — notification didn't send, but you can still launch it now."
              : "Notification sent — check your phone to launch it."}
          </span>
        </div>
        <a href={`/publish/${post.id}`} className="underline">Open launch page</a>
      </div>
    );
  }

  if (post.status === "failed" || post.status === "needs_reconnect") {
    return (
      <div className="flex items-start gap-1.5 text-xs text-red-500 mt-1">
        <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        <span className="line-clamp-2">
          {post.status === "needs_reconnect" ? "Reconnect this account in Settings" : (post.error ?? "Something went wrong")}
        </span>
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 space-y-1.5">
      <div className="flex items-center gap-3 text-xs text-gray-600">
        {post.latest_views != null && (
          <span className="flex items-center gap-1"><Eye className="h-3 w-3 text-gray-400" />{post.latest_views.toLocaleString()}</span>
        )}
        {post.latest_likes != null && (
          <span className="flex items-center gap-1"><Heart className="h-3 w-3 text-gray-400" />{post.latest_likes.toLocaleString()}</span>
        )}
        {post.latest_comments != null && (
          <span className="flex items-center gap-1"><MessageCircle className="h-3 w-3 text-gray-400" />{post.latest_comments.toLocaleString()}</span>
        )}
        <button onClick={refresh} disabled={refreshing} title="Refresh now" className="ml-auto text-gray-300 hover:text-gray-500">
          <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />
        </button>
      </div>
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>{post.created_via === "published" ? "Published by Culturix" : "Tracked"} · {timeAgo(post.last_fetched_at ?? post.posted_at)}</span>
        {post.post_url && (
          <a href={post.post_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-blue-500 hover:text-blue-600">
            View <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </div>
  );
}

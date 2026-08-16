"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import ConfirmDialog from "@/components/ui/ConfirmDialog";

// Global actions only — per-page titles/refresh live in each routed page
// now that sections are separate routes rather than one shared view-state.
export default function AdminTopBar() {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [collectMsg, setCollectMsg] = useState("");

  async function triggerCollect() {
    setCollecting(true);
    setCollectMsg("");
    try {
      const res = await fetch("/api/admin/collect", { method: "POST" });
      setCollectMsg(res.ok ? "Collection started — refresh in ~60s" : `Error ${res.status}`);
    } catch (e) {
      setCollectMsg(`Error: ${e}`);
    } finally {
      setCollecting(false);
      setConfirmOpen(false);
    }
  }

  return (
    <header className="h-16 bg-white border-b border-gray-100 flex items-center justify-end px-8 gap-3 shrink-0">
      {collectMsg && <span className="text-xs text-gray-400">{collectMsg}</span>}
      <button
        onClick={() => setConfirmOpen(true)}
        disabled={collecting}
        className="px-4 py-1.5 bg-primary-600 text-white text-sm rounded-lg hover:bg-primary-700 disabled:opacity-50 transition inline-flex items-center gap-1.5"
      >
        <RefreshCw className="h-3.5 w-3.5" />
        {collecting ? "Collecting…" : "Collect now"}
      </button>
      <a
        href="/dashboard"
        className="px-4 py-1.5 border border-gray-200 text-gray-600 text-sm rounded-lg hover:bg-gray-50 transition"
      >
        ← User dashboard
      </a>

      <ConfirmDialog
        open={confirmOpen}
        title="Trigger a full collection run?"
        description="This kicks off a real scrape across every source (YouTube, Twitter, Reddit, TikTok, Xiaohongshu, Pinterest, Wikipedia, Bluesky) right now, outside the normal schedule."
        confirmLabel="Collect now"
        loading={collecting}
        onConfirm={triggerCollect}
        onCancel={() => setConfirmOpen(false)}
      />
    </header>
  );
}

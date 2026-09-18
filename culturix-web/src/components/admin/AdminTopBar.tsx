"use client";

import { useState } from "react";
import { Menu, RefreshCw } from "lucide-react";
import ConfirmDialog from "@/components/ui/ConfirmDialog";

// Global actions only — per-page titles/refresh live in each routed page
// now that sections are separate routes rather than one shared view-state.
// On small screens the menu button opens the nav drawer, "Collect now"
// shrinks to an icon, and the "User dashboard" link (also in the drawer as
// "Back to app") is hidden so nothing overflows a 375px-wide header.
export default function AdminTopBar({ onMenu, menuOpen }: { onMenu: () => void; menuOpen: boolean }) {
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
    <header className="h-16 bg-white border-b border-gray-100 flex items-center px-4 sm:px-6 lg:px-8 gap-3 shrink-0">
      <button
        type="button"
        onClick={onMenu}
        aria-label="Open menu"
        aria-expanded={menuOpen}
        className="lg:hidden -ml-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-gray-600 hover:bg-gray-50"
      >
        <Menu className="h-5 w-5" />
      </button>
      <span className="lg:hidden font-bold text-base tracking-tight text-gray-900">Admin</span>

      <div className="ml-auto flex min-w-0 items-center gap-3">
        {collectMsg && <span className="hidden sm:block truncate text-xs text-gray-400">{collectMsg}</span>}
        <button
          onClick={() => setConfirmOpen(true)}
          disabled={collecting}
          aria-label="Collect now"
          className="h-11 min-w-11 px-3 sm:px-4 lg:h-auto lg:py-1.5 bg-primary-600 text-white text-sm rounded-lg hover:bg-primary-700 disabled:opacity-50 transition inline-flex items-center justify-center gap-1.5"
        >
          <RefreshCw className={`h-4 w-4 lg:h-3.5 lg:w-3.5 ${collecting ? "animate-spin" : ""}`} />
          <span className="hidden sm:inline">{collecting ? "Collecting…" : "Collect now"}</span>
        </button>
        <a
          href="/dashboard"
          className="hidden lg:inline-block px-4 py-1.5 border border-gray-200 text-gray-600 text-sm rounded-lg hover:bg-gray-50 transition whitespace-nowrap"
        >
          ← User dashboard
        </a>
      </div>

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

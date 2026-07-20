"use client";

import { useState } from "react";
import { Check, RefreshCw } from "lucide-react";

interface Props {
  profileId?: string;
}

export default function RefreshButton({ profileId }: Props) {
  const [state, setState] = useState<"idle" | "loading" | "started">("idle");

  async function handleClick() {
    setState("loading");
    try {
      const body = new FormData();
      if (profileId) body.set("profile_id", profileId);
      // fetch (not a native form submit) so we can show real feedback instead
      // of an instant full-page reload — the backend pipeline this kicks off
      // runs in the background and takes real time (multiple AI calls per
      // profile), so reloading immediately just shows the same old digest
      // with nothing to indicate a refresh is actually in progress.
      const res = await fetch("/api/generate", { method: "POST", body });
      setState(res.ok ? "started" : "idle");
    } catch {
      setState("idle");
    }
  }

  if (state === "started") {
    return (
      <span className="inline-flex items-center gap-2 text-sm font-medium text-green-700 border border-green-200 bg-green-50 rounded-lg px-3 py-2">
        <Check className="h-3.5 w-3.5" /> Refresh started — reload in a minute or two
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={state === "loading"}
      className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors disabled:opacity-60"
    >
      <RefreshCw className={`h-3.5 w-3.5 ${state === "loading" ? "animate-spin" : ""}`} />
      {state === "loading" ? "Starting…" : "Refresh"}
    </button>
  );
}

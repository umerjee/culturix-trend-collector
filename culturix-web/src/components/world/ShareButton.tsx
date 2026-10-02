"use client";

import { useEffect, useState } from "react";
import { Share2, Check } from "lucide-react";
import { useLocale } from "@/components/i18n/LocaleProvider";

// Web Share sheet where the browser has one (phones, most tablets), copy-to-clipboard otherwise.
export default function ShareButton({
  path, title, variant = "light", compact = false,
}: {
  path: string; title: string; variant?: "light" | "dark"; compact?: boolean;
}) {
  const { messages } = useLocale();
  const t = messages.world;
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(id);
  }, [copied]);

  async function share() {
    const url = new URL(path, window.location.origin).toString();
    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ title, url });
        return;
      } catch (e) {
        if ((e as DOMException)?.name === "AbortError") return;
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      window.prompt(t.share, url);
    }
  }

  const base = "inline-flex items-center justify-center gap-1.5 min-h-[44px] min-w-[44px] rounded-full text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-400";
  const look = variant === "dark"
    ? "bg-black/40 text-white backdrop-blur-sm hover:bg-black/60"
    : "border border-gray-200 bg-white px-4 text-gray-700 hover:bg-gray-50";

  return (
    <>
      <button type="button" onClick={share} aria-label={t.share} className={`${base} ${look}`}>
        {copied ? <Check className="h-5 w-5" aria-hidden="true" /> : <Share2 className={compact ? "h-5 w-5" : "h-4 w-4"} aria-hidden="true" />}
        {!compact && <span>{copied ? t.linkCopied : t.share}</span>}
      </button>
      <span className="sr-only" aria-live="polite">{copied ? t.linkCopied : ""}</span>
    </>
  );
}

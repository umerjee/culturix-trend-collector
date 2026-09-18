import { ExternalLink, Heart } from "lucide-react";
import type { WorldTrend } from "@/lib/worldTypes";

const PLATFORM_COLORS: Record<string, string> = {
  tiktok: "bg-pink-50 text-pink-600",
  youtube: "bg-red-50 text-red-600",
  instagram: "bg-purple-50 text-purple-600",
  twitter: "bg-sky-50 text-sky-600",
  reddit: "bg-orange-50 text-orange-600",
  google_trends: "bg-blue-50 text-blue-600",
  wikipedia: "bg-gray-100 text-gray-600",
  bluesky: "bg-cyan-50 text-cyan-600",
  pinterest: "bg-rose-50 text-rose-600",
  xiaohongshu: "bg-red-50 text-red-500",
};

function platformLabel(platform: string): string {
  if (platform === "google_trends") return "Google Trends";
  return platform.charAt(0).toUpperCase() + platform.slice(1);
}

export default function TrendFeed({ trends }: { trends: WorldTrend[] }) {
  if (trends.length === 0) return null;

  return (
    <div className="space-y-3">
      {trends.map((t) => (
        <div key={`${t.platform}-${t.id}`} className="rounded-xl border border-gray-100 p-4 flex items-start gap-3">
          <span className={`shrink-0 inline-flex items-center rounded-full text-[11px] font-semibold px-2 py-0.5 ${PLATFORM_COLORS[t.platform] || "bg-gray-100 text-gray-600"}`}>
            {platformLabel(t.platform)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm text-gray-800 leading-snug">{t.title || t.content}</p>
            {t.title && t.content && t.content !== t.title && (
              <p className="text-xs text-gray-400 mt-1 line-clamp-2">{t.content}</p>
            )}
          </div>
          <div className="shrink-0 flex items-center gap-3 text-xs text-gray-400">
            {/* Explicit locale on toLocaleString below — with no argument it
                follows the runtime's default locale, which differs between
                the Node server (this machine's system locale) and the
                browser, producing different digit-group separators
                ("4'929" vs "4,929") and breaking hydration. Confirmed live
                via a real browser console error before this fix. */}
            {typeof t.likes === "number" && t.likes > 0 && (
              <span className="flex items-center gap-1"><Heart className="h-3 w-3" /> {t.likes.toLocaleString("en-US")}</span>
            )}
            {t.url && (
              <a href={t.url} target="_blank" rel="noopener noreferrer" className="hover:text-purple-600">
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

import { Music, Target, Megaphone, ArrowUpRight } from "lucide-react";
import type { ContentIdea } from "@/lib/types";

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
}

export default function DigestCard({ idea, index }: Props) {
  const platformColor = PLATFORM_COLORS[idea.platform] ?? "bg-gray-100 text-gray-700";

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-3 mb-4">
        <span className="text-xs font-bold text-gray-300">#{String(index + 1).padStart(2, "0")}</span>
        <span className={`text-xs font-semibold rounded-full px-2.5 py-1 ${platformColor}`}>
          {idea.platform}
        </span>
      </div>

      {/* Hook */}
      <p className="text-base font-bold text-gray-900 leading-snug mb-3">{idea.hook}</p>

      {/* Caption */}
      <p className="text-sm text-gray-600 leading-relaxed mb-4 line-clamp-3">{idea.caption}</p>

      <div className="space-y-2 border-t border-gray-50 pt-4">
        {/* CTA */}
        <div className="flex items-start gap-2">
          <Megaphone className="h-3.5 w-3.5 text-blue-500 mt-0.5 shrink-0" />
          <p className="text-xs text-gray-600">{idea.cta}</p>
        </div>

        {/* Music mood */}
        {idea.music_mood && (
          <div className="flex items-center gap-2">
            <Music className="h-3.5 w-3.5 text-purple-400 shrink-0" />
            <p className="text-xs text-gray-500">{idea.music_mood}</p>
          </div>
        )}

        {/* Trend connection */}
        {idea.trend_connection && (
          <div className="flex items-start gap-2">
            <Target className="h-3.5 w-3.5 text-green-500 mt-0.5 shrink-0" />
            <p className="text-xs text-gray-500">{idea.trend_connection}</p>
          </div>
        )}
      </div>
    </div>
  );
}

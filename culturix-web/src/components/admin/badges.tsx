import { ArrowUpRight, ArrowDownRight, Minus } from "lucide-react";

const PATTERN_BADGE: Record<string, string> = {
  weekly: "bg-primary-100 text-primary-700",
  yearly: "bg-violet-100 text-violet-700",
  sustained: "bg-green-100 text-green-700",
  spike: "bg-orange-100 text-orange-700",
  unclear: "bg-gray-100 text-gray-500",
};
export const PATTERN_LABEL: Record<string, string> = {
  weekly: "Weekly", yearly: "Yearly", sustained: "Sustained", spike: "Spike", unclear: "Unclear",
};
export const PATTERN_ORDER = ["weekly", "yearly", "sustained", "spike", "unclear"];

export function PatternBadge({ pattern }: { pattern: string | null }) {
  const p = pattern ?? "unclear";
  return (
    <span className={`shrink-0 px-2 py-0.5 rounded text-xs font-semibold ${PATTERN_BADGE[p] ?? PATTERN_BADGE.unclear}`}>
      {PATTERN_LABEL[p] ?? "Unclear"}
    </span>
  );
}

export function MomentumBadge({ momentum }: { momentum?: "up" | "down" | "neutral" | null }) {
  if (!momentum) return null;
  if (momentum === "up") {
    return <span className="inline-flex items-center gap-0.5 text-xs font-semibold text-green-600"><ArrowUpRight className="h-3.5 w-3.5" /> Rising</span>;
  }
  if (momentum === "down") {
    return <span className="inline-flex items-center gap-0.5 text-xs font-semibold text-red-500"><ArrowDownRight className="h-3.5 w-3.5" /> Falling</span>;
  }
  return <span className="inline-flex items-center gap-0.5 text-xs font-medium text-gray-400"><Minus className="h-3.5 w-3.5" /> Steady</span>;
}

const PLATFORM_BADGE: Record<string, string> = {
  youtube: "bg-red-100 text-red-600",
  twitter: "bg-sky-100 text-sky-600",
  reddit: "bg-orange-100 text-orange-600",
  tiktok: "bg-pink-100 text-pink-600",
};

export function PlatformBadge({ platform }: { platform: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold capitalize ${PLATFORM_BADGE[platform] ?? "bg-gray-100 text-gray-500"}`}>
      {platform === "youtube" ? "YouTube" : platform.charAt(0).toUpperCase() + platform.slice(1)}
    </span>
  );
}

export function StatCard({ icon, value, label }: { icon: React.ReactNode; value: number | string; label: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-6 flex flex-col gap-3">
      <div className="h-10 w-10 rounded-xl bg-gray-50 flex items-center justify-center text-gray-500">
        {icon}
      </div>
      <div>
        <p className="text-3xl font-bold text-gray-900">{value}</p>
        <p className="text-sm text-gray-500 mt-0.5">{label}</p>
      </div>
    </div>
  );
}

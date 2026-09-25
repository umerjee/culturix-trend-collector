import type { WorldSentimentHistory } from "@/lib/worldTypes";

// Real daily mood/sentiment history (see GET /world/regions/{code}/sentiment-history) as a
// small inline-SVG line — no charting library needed for a handful of points. A day with
// no summary computed is simply absent from `days`, so gaps in the line are honest, not
// interpolated-away.
const MOOD_COLOR: Record<string, string> = {
  celebratory: "#d97706", playful: "#db2777", curious: "#0284c7", tense: "#ea580c",
  somber: "#64748b", angry: "#dc2626", neutral: "#9ca3af",
};

export default function SentimentSparkline({ history }: { history: WorldSentimentHistory | null }) {
  const days = history?.days ?? [];
  if (days.length < 2) return null;

  const width = 280;
  const height = 56;
  const padY = 8;
  const values = days.map((d) => d.sentiment ?? 0);
  const min = Math.min(-2, ...values);
  const max = Math.max(2, ...values);
  const range = max - min || 1;
  const stepX = width / (days.length - 1);
  const points = values.map((v, i) => {
    const x = i * stepX;
    const y = padY + (1 - (v - min) / range) * (height - padY * 2);
    return { x, y, day: days[i] };
  });
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const last = points[points.length - 1];

  return (
    <div className="mb-8 rounded-2xl border border-gray-100 bg-white p-4 sm:p-5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
          Mood, last {days.length} days
        </span>
        {days[days.length - 1].mood && (
          <span className="text-xs font-medium capitalize text-gray-600">{days[days.length - 1].mood}</span>
        )}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="mt-2 w-full" preserveAspectRatio="none" role="img"
           aria-label={`Sentiment trend over the last ${days.length} days`}>
        <line x1="0" y1={padY + (1 - (0 - min) / range) * (height - padY * 2)}
              x2={width} y2={padY + (1 - (0 - min) / range) * (height - padY * 2)}
              stroke="#f3f4f6" strokeWidth="1" />
        <path d={path} fill="none" stroke="#a78bfa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={last.x} cy={last.y} r="3" fill={MOOD_COLOR[last.day.mood || ""] || "#7c3aed"} />
      </svg>
    </div>
  );
}

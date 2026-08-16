import type { TrendOccurrence } from "@/lib/admin/types";

// Dot-plot timeline of occurrence dates between first and last seen —
// makes recurrence (evenly spaced dots) vs a one-off burst (clustered dots) visible at a glance.
export default function OccurrenceTimeline({ occurrences }: { occurrences: TrendOccurrence[] }) {
  if (occurrences.length === 0) {
    return <p className="text-xs text-gray-400">No occurrences yet.</p>;
  }
  const dates = occurrences.map((o) => new Date(o.occurrence_date).getTime()).sort((a, b) => a - b);
  const min = dates[0];
  const max = dates[dates.length - 1];
  const span = Math.max(max - min, 1);

  return (
    <div className="relative h-9">
      <div className="absolute inset-x-0 top-1/2 h-px bg-gray-200" />
      {dates.map((d, i) => (
        <div
          key={i}
          className="absolute top-1/2 h-2.5 w-2.5 rounded-full bg-primary-600 ring-2 ring-white hover:scale-125 transition-transform cursor-default"
          style={{ left: `${((d - min) / span) * 100}%`, transform: "translate(-50%, -50%)" }}
          title={new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
        />
      ))}
      <div className="absolute inset-x-0 -bottom-1 flex justify-between text-[10px] text-gray-400">
        <span>{new Date(min).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
        {max !== min && <span>{new Date(max).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>}
      </div>
    </div>
  );
}

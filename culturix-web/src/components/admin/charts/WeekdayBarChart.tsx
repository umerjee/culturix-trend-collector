import type { TrendOccurrence } from "@/lib/admin/types";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WEEKDAYS_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export { WEEKDAYS, WEEKDAYS_FULL };

// Occurrence count per weekday, single-hue bars (magnitude, not identity) —
// the dominant day (if any) is rendered as the darker step of the same hue.
export default function WeekdayBarChart({ occurrences, dominantDay }: { occurrences: TrendOccurrence[]; dominantDay: number | null }) {
  const counts = [0, 0, 0, 0, 0, 0, 0];
  occurrences.forEach((o) => { if (o.day_of_week >= 0 && o.day_of_week <= 6) counts[o.day_of_week] += 1; });
  const max = Math.max(...counts, 1);

  return (
    <div className="flex items-end gap-2 h-28">
      {counts.map((count, i) => (
        <div key={i} className="flex-1 flex flex-col items-center gap-1.5">
          <div className="w-full flex flex-col justify-end h-20">
            <div
              className={`w-full rounded-t transition-colors ${i === dominantDay ? "bg-primary-600" : "bg-primary-200 hover:bg-primary-300"}`}
              style={{ height: count === 0 ? "2px" : `${Math.max((count / max) * 100, 8)}%` }}
              title={`${WEEKDAYS_FULL[i]}: ${count} occurrence${count !== 1 ? "s" : ""}`}
            />
          </div>
          <span className={`text-[10px] font-medium ${i === dominantDay ? "text-primary-600" : "text-gray-400"}`}>{WEEKDAYS[i]}</span>
        </div>
      ))}
    </div>
  );
}

import { cn } from "@/lib/cn";

interface Props {
  label: string;
  value: string;
  className?: string;
}

// Standardizes the stat-tile pattern previously copy-pasted across
// dashboard/page.tsx, dashboard/performance/page.tsx, and admin's Overview.
export default function StatTile({ label, value, className }: Props) {
  return (
    <div className={cn("rounded-xl bg-white border border-gray-100 px-4 py-3", className)}>
      <p className="text-xl font-bold text-primary-600 leading-none">{value}</p>
      <p className="text-xs text-gray-400 mt-1">{label}</p>
    </div>
  );
}

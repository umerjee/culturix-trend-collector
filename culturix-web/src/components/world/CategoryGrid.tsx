import Link from "next/link";
import { Landmark, Sparkles, Fish, Cpu, LayoutGrid } from "lucide-react";
import { CATEGORY_LABELS } from "@/lib/worldTypes";

const CATEGORY_ICONS: Record<string, typeof Landmark> = {
  place: Landmark,
  phenomenon: Sparkles,
  species: Fish,
  tech: Cpu,
  custom: LayoutGrid,
};

export default function CategoryGrid() {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
      {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
        const Icon = CATEGORY_ICONS[key] || LayoutGrid;
        return (
          <Link
            key={key}
            href={`/world?category=${key}`}
            className="rounded-2xl border border-gray-100 p-4 text-center hover:border-purple-200 transition-colors"
          >
            <div className="h-9 w-9 rounded-xl bg-purple-50 flex items-center justify-center mx-auto mb-2">
              <Icon className="h-4 w-4 text-purple-500" />
            </div>
            <span className="text-xs font-medium text-gray-700">{label}</span>
          </Link>
        );
      })}
    </div>
  );
}

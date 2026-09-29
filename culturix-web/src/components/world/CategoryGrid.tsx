import { CATEGORY_LABELS } from "@/lib/worldTypes";
import { CATEGORY_ICONS, CATEGORY_COLORS } from "@/lib/worldCategoryVisuals";
import { LayoutGrid } from "lucide-react";

// Also usable as an inline filter toggle (see WorldExplorer): pass `active` + `onSelect` to run
// it as buttons that highlight the current category instead of navigating away. Falls back to
// plain links (the original behavior) when `onSelect` is omitted, so any other page that still
// wants simple navigation keeps working unchanged.
export default function CategoryGrid({
  active, onSelect,
}: { active?: string | null; onSelect?: (category: string | null) => void } = {}) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
      {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
        const Icon = CATEGORY_ICONS[key] || LayoutGrid;
        const color = CATEGORY_COLORS[key];
        const isActive = active === key;
        const content = (
          <>
            <div
              className="h-9 w-9 rounded-xl flex items-center justify-center mx-auto mb-2 transition-colors"
              style={{ background: isActive ? color : `${color}1a` }}
            >
              <Icon className="h-4 w-4" style={{ color: isActive ? "#fff" : color }} />
            </div>
            <span className={`text-xs font-medium ${isActive ? "text-gray-900" : "text-gray-700"}`}>{label}</span>
          </>
        );
        const className = `rounded-2xl border p-4 text-center transition-colors ${
          isActive ? "border-gray-900" : "border-gray-100 hover:border-purple-200"
        }`;
        if (onSelect) {
          return (
            <button key={key} type="button" onClick={() => onSelect(isActive ? null : key)} className={className} aria-pressed={isActive}>
              {content}
            </button>
          );
        }
        return (
          <a key={key} href={`/world?category=${key}`} className={className}>
            {content}
          </a>
        );
      })}
    </div>
  );
}

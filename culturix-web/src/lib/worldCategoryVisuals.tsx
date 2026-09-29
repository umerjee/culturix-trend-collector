import { Landmark, Sparkles, Fish, Cpu, Flame, LayoutGrid } from "lucide-react";

// Single source of truth for how a category LOOKS, reused by CategoryGrid (the browse tiles),
// WorldMap (per-category markers) and FeatureCard (the badge on each card) so the same subject
// reads as the same icon/color everywhere on the site. Previously each of those hard-coded its
// own copy (CategoryGrid's own CATEGORY_ICONS, the map's plain uncategorized purple dot) — real
// UX inconsistency: nothing on the map or the card grid gave any visual hint of WHAT KIND of
// content a marker/card was before you clicked it.
export const CATEGORY_ICONS: Record<string, typeof Landmark> = {
  place: Landmark,
  phenomenon: Sparkles,
  species: Fish,
  tech: Cpu,
  genz: Flame,
  custom: LayoutGrid,
};

// Distinct hues, chosen to stay legible against the map's sky-blue ocean and white country fill
// (tech's blue is a deeper #2563eb rather than sky-shade, so it doesn't blend into the ocean).
export const CATEGORY_COLORS: Record<string, string> = {
  place: "#7c3aed", // violet
  phenomenon: "#f59e0b", // amber
  species: "#10b981", // emerald
  tech: "#2563eb", // blue
  genz: "#ec4899", // pink
  custom: "#64748b", // slate
};

export const DEFAULT_CATEGORY_COLOR = "#64748b";

export function iconForCategory(category: string | null | undefined) {
  return CATEGORY_ICONS[category || ""] || LayoutGrid;
}

export function colorForCategory(category: string | null | undefined): string {
  return CATEGORY_COLORS[category || ""] || DEFAULT_CATEGORY_COLOR;
}

// Picks the category with the highest count for a region's {category: count} breakdown —
// used to choose ONE icon/color for a map marker representing possibly-mixed content.
export function dominantCategory(categories: Record<string, number> | undefined): string | null {
  if (!categories) return null;
  let best: string | null = null;
  let bestCount = 0;
  for (const [cat, count] of Object.entries(categories)) {
    if (count > bestCount) { best = cat; bestCount = count; }
  }
  return best;
}

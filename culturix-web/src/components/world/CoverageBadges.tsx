import { CATEGORY_LABELS } from "@/lib/worldTypes";
import type { WorldFeatureCoverage } from "@/lib/worldTypes";

// Real category/era breakdown of this region's published catalog (see GET /world/regions/
// {code}/coverage) — makes gaps visible ("0 species covered so far") and shows the real
// era span videos here actually cover, computed from Toon rows already in the database.
export default function CoverageBadges({ coverage }: { coverage: WorldFeatureCoverage | null }) {
  const categories = coverage?.categories ?? {};
  const entries = Object.entries(categories);
  if (entries.length === 0) return null;

  const eraSpan = coverage?.era_year_min != null && coverage?.era_year_max != null
    ? `${yearLabel(coverage.era_year_min)} – ${yearLabel(coverage.era_year_max)}`
    : null;

  return (
    <div className="mb-5 flex flex-wrap items-center gap-2 text-xs">
      {entries.map(([category, count]) => (
        <span key={category} className="inline-flex items-center gap-1 rounded-full border border-gray-100 bg-gray-50 px-2.5 py-1 text-gray-600">
          <span className="font-semibold text-gray-800">{count}</span> {CATEGORY_LABELS[category] || category}
        </span>
      ))}
      {eraSpan && (
        <span className="inline-flex items-center rounded-full border border-purple-100 bg-purple-50 px-2.5 py-1 text-purple-600">
          Spans {eraSpan}
        </span>
      )}
    </div>
  );
}

function yearLabel(year: number): string {
  return year < 0 ? `${-year} BC` : `${year}`;
}

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ComposableMap, Geographies, Geography } from "react-simple-maps";
import countries from "i18n-iso-countries";
import enLocale from "i18n-iso-countries/langs/en.json";
import worldTopoJson from "world-atlas/countries-110m.json";

countries.registerLocale(enLocale as any);

// world-atlas's topojson feature `id` is an ISO 3166-1 NUMERIC code (e.g.
// "840" for the US), not the ISO-2 alpha code our backend stores on
// Toon.subject_region/Trend.region — i18n-iso-countries bridges the two
// rather than hand-maintaining a numeric<->alpha2 table here.
const GEO_URL = worldTopoJson as unknown as Parameters<typeof Geographies>[0]["geography"];

interface RegionCount {
  region: string;
  count: number;
}

// A handful of buckets is plenty here — World content is admin-curated one
// Feature at a time (see scripts/generate_world_feature.py), so even a
// "lot of content" region realistically means single digits for a long
// while, not hundreds.
function fillForCount(count: number): string {
  if (count >= 5) return "#6d28d9"; // purple-700
  if (count >= 2) return "#8b5cf6"; // purple-500
  return "#c4b5fd"; // purple-300
}

export default function WorldMap() {
  const router = useRouter();
  const [regionCounts, setRegionCounts] = useState<Record<string, number>>({});
  const [hovered, setHovered] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/world/regions")
      .then((r) => (r.ok ? r.json() : { regions: [] }))
      .then((data: { regions: RegionCount[] }) => {
        const map: Record<string, number> = {};
        for (const r of data.regions || []) map[r.region] = r.count;
        setRegionCounts(map);
      })
      .catch(() => setRegionCounts({}));
  }, []);

  return (
    <div className="relative">
      <ComposableMap
        projectionConfig={{ scale: 147 }}
        className="w-full h-auto"
        style={{ maxHeight: 420 }}
      >
        <Geographies geography={GEO_URL}>
          {({ geographies }) =>
            geographies.map((geo) => {
              const alpha2 = countries.numericToAlpha2(geo.id as string);
              const count = alpha2 ? regionCounts[alpha2] || 0 : 0;
              const hasContent = count > 0;
              return (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  onMouseEnter={() => hasContent && alpha2 && setHovered(alpha2)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => hasContent && alpha2 && router.push(`/world/region/${alpha2}`)}
                  style={{
                    default: {
                      fill: hasContent ? fillForCount(count) : "#e5e7eb",
                      stroke: "#ffffff",
                      strokeWidth: 0.5,
                      outline: "none",
                      cursor: hasContent ? "pointer" : "default",
                    },
                    hover: {
                      fill: hasContent ? "#4c1d95" : "#e5e7eb",
                      stroke: "#ffffff",
                      strokeWidth: 0.5,
                      outline: "none",
                      cursor: hasContent ? "pointer" : "default",
                    },
                    pressed: {
                      fill: "#4c1d95",
                      stroke: "#ffffff",
                      strokeWidth: 0.5,
                      outline: "none",
                    },
                  }}
                />
              );
            })
          }
        </Geographies>
      </ComposableMap>
      {hovered && (
        <div className="absolute top-2 left-2 rounded-lg bg-gray-900 text-white text-xs font-medium px-2.5 py-1.5 pointer-events-none">
          {countries.getName(hovered, "en") || hovered} — {regionCounts[hovered]} feature
          {regionCounts[hovered] === 1 ? "" : "s"}
        </div>
      )}
      {Object.keys(regionCounts).length === 0 && (
        <p className="text-center text-sm text-gray-400 mt-4">
          No World Features published yet — check back soon.
        </p>
      )}
    </div>
  );
}

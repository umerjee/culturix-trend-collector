"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  ComposableMap, Geographies, Geography, ZoomableGroup, Sphere, Graticule,
} from "react-simple-maps";
import { Plus, Minus, RotateCcw } from "lucide-react";
import countries from "i18n-iso-countries";
import enLocale from "i18n-iso-countries/langs/en.json";
import worldTopoJson from "world-atlas/countries-110m.json";

countries.registerLocale(enLocale as any);

// world-atlas's topojson feature `id` is an ISO 3166-1 NUMERIC code (e.g.
// "840" for the US), not the ISO-2 alpha code our backend stores on
// Toon.subject_region/Trend.region — i18n-iso-countries bridges the two
// rather than hand-maintaining a numeric<->alpha2 table here.
const GEO_URL = worldTopoJson as unknown as Parameters<typeof Geographies>[0]["geography"];

const MIN_ZOOM = 1;
const MAX_ZOOM = 8;
const DEFAULT_POSITION = { coordinates: [0, 20] as [number, number], zoom: 1 };

interface RegionCount {
  region: string;
  count: number;
  feature_count: number;
  trend_count: number;
  trend_days: number;
}

// A handful of buckets is plenty here — World content is admin-curated one
// Feature at a time (see scripts/generate_world_feature.py), so even a
// "lot of content" region realistically means single digits for a long
// while, not hundreds.
const BUCKETS: [number, string][] = [
  [5, "#5b21b6"],  // purple-800
  [2, "#8b5cf6"],  // purple-500
  [1, "#c4b5fd"],  // purple-300
];

function fillForCount(count: number): string {
  for (const [min, color] of BUCKETS) {
    if (count >= min) return color;
  }
  return "#e2e8f0"; // slate-200, no content
}

export default function WorldMap() {
  const router = useRouter();
  const [regionCounts, setRegionCounts] = useState<Record<string, RegionCount>>({});
  const [hovered, setHovered] = useState<{ code: string; x: number; y: number } | null>(null);
  const [position, setPosition] = useState(DEFAULT_POSITION);

  useEffect(() => {
    fetch("/api/world/regions")
      .then((r) => (r.ok ? r.json() : { regions: [] }))
      .then((data: { regions: RegionCount[] }) => {
        const map: Record<string, RegionCount> = {};
        for (const r of data.regions || []) map[r.region] = r;
        setRegionCounts(map);
      })
      .catch(() => setRegionCounts({}));
  }, []);

  const zoomBy = useCallback((factor: number) => {
    setPosition((pos) => ({ ...pos, zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, pos.zoom * factor)) }));
  }, []);

  const resetView = useCallback(() => setPosition(DEFAULT_POSITION), []);

  return (
    <div className="relative rounded-2xl overflow-hidden border border-gray-100 bg-gradient-to-b from-sky-50 to-white">
      <ComposableMap
        projectionConfig={{ scale: 148 }}
        className="w-full h-auto"
        style={{ maxHeight: 480 }}
        onMouseMove={(e) => {
          if (hovered) setHovered((h) => (h ? { ...h, x: e.clientX, y: e.clientY } : h));
        }}
      >
        <ZoomableGroup
          center={position.coordinates}
          zoom={position.zoom}
          minZoom={MIN_ZOOM}
          maxZoom={MAX_ZOOM}
          onMoveEnd={({ coordinates, zoom }) => setPosition({ coordinates, zoom })}
        >
          <Sphere id="world-sphere" fill="transparent" stroke="#bae6fd" strokeWidth={0.5} />
          <Graticule stroke="#e0f2fe" strokeWidth={0.5} />
          <Geographies geography={GEO_URL}>
            {({ geographies }) =>
              geographies.map((geo) => {
                const alpha2 = countries.numericToAlpha2(geo.id as string);
                const stats = alpha2 ? regionCounts[alpha2] : undefined;
                const activity = stats ? stats.feature_count + Math.min(stats.trend_count, 5) : 0;
                const hasContent = Boolean(stats && (stats.feature_count > 0 || stats.trend_count > 0));
                return (
                  <Geography
                    key={geo.rsmKey}
                    geography={geo}
                    onMouseEnter={(e) => hasContent && alpha2 && setHovered({ code: alpha2, x: e.clientX, y: e.clientY })}
                    onMouseLeave={() => setHovered(null)}
                    onClick={() => hasContent && alpha2 && router.push(`/world/region/${alpha2}`)}
                    style={{
                      default: {
                        fill: fillForCount(activity),
                        stroke: "#ffffff",
                        strokeWidth: 0.5 / position.zoom,
                        outline: "none",
                        cursor: hasContent ? "pointer" : "default",
                        transition: "fill 150ms ease",
                      },
                      hover: {
                        fill: hasContent ? "#4c1d95" : "#cbd5e1",
                        stroke: "#ffffff",
                        strokeWidth: 0.5 / position.zoom,
                        outline: "none",
                        cursor: hasContent ? "pointer" : "default",
                      },
                      pressed: {
                        fill: "#3b0764",
                        stroke: "#ffffff",
                        strokeWidth: 0.5 / position.zoom,
                        outline: "none",
                      },
                    }}
                  />
                );
              })
            }
          </Geographies>
        </ZoomableGroup>
      </ComposableMap>

      {/* Zoom controls */}
      <div className="absolute bottom-3 right-3 flex flex-col rounded-xl border border-gray-200 bg-white/95 backdrop-blur-sm shadow-sm overflow-hidden">
        <button
          type="button"
          aria-label="Zoom in"
          onClick={() => zoomBy(1.5)}
          disabled={position.zoom >= MAX_ZOOM}
          className="h-8 w-8 flex items-center justify-center text-gray-600 hover:bg-purple-50 hover:text-purple-600 disabled:opacity-30 disabled:hover:bg-transparent border-b border-gray-100"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() => zoomBy(1 / 1.5)}
          disabled={position.zoom <= MIN_ZOOM}
          className="h-8 w-8 flex items-center justify-center text-gray-600 hover:bg-purple-50 hover:text-purple-600 disabled:opacity-30 disabled:hover:bg-transparent border-b border-gray-100"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Reset view"
          onClick={resetView}
          className="h-8 w-8 flex items-center justify-center text-gray-600 hover:bg-purple-50 hover:text-purple-600"
        >
          <RotateCcw className="h-3 w-3" />
        </button>
      </div>

      {/* Legend */}
      <div className="absolute bottom-3 left-3 rounded-xl border border-gray-200 bg-white/95 backdrop-blur-sm shadow-sm px-3 py-2 text-[11px] text-gray-600 flex items-center gap-3">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "#c4b5fd" }} />1+
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "#8b5cf6" }} />2+
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "#5b21b6" }} />5+
        </span>
      </div>

      {hovered && (
        <div
          className="fixed z-50 rounded-lg bg-gray-900 text-white text-xs font-medium px-2.5 py-1.5 pointer-events-none shadow-lg"
          style={{ left: hovered.x + 12, top: hovered.y + 12 }}
        >
          {countries.getName(hovered.code, "en") || hovered.code} — {regionCounts[hovered.code]?.feature_count || 0} feature{regionCounts[hovered.code]?.feature_count === 1 ? "" : "s"}
          {regionCounts[hovered.code]?.trend_count ? ` · ${regionCounts[hovered.code].trend_count} trend${regionCounts[hovered.code].trend_count === 1 ? "" : "s"}` : ""}
        </div>
      )}

      {Object.keys(regionCounts).length === 0 && (
        <p className="absolute inset-x-0 bottom-1/2 translate-y-1/2 text-center text-sm text-gray-400">
          No World Features published yet — check back soon.
        </p>
      )}
    </div>
  );
}

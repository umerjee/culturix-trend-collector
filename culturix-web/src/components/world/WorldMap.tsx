"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  ComposableMap, Geographies, Geography, ZoomableGroup, Sphere, Graticule, Marker,
} from "react-simple-maps";
import type { ProjectionFunction } from "react-simple-maps";
import { geoOrthographic, geoCentroid, geoDistance } from "d3-geo";
import { Plus, Minus, RotateCcw, Globe2, Map as MapIcon } from "lucide-react";
import countries from "i18n-iso-countries";
import enLocale from "i18n-iso-countries/langs/en.json";
import worldTopoJson from "world-atlas/countries-110m.json";

countries.registerLocale(enLocale as any);

// world-atlas's topojson feature `id` is an ISO 3166-1 NUMERIC code (e.g.
// "840" for the US), not the ISO-2 alpha code our backend stores on
// Toon.subject_region/Trend.region — i18n-iso-countries bridges the two
// rather than hand-maintaining a numeric<->alpha2 table here.
const GEO_URL = worldTopoJson as unknown as Parameters<typeof Geographies>[0]["geography"];

const WIDTH = 800;
const HEIGHT = 500;

const FLAT_MIN_ZOOM = 1;
const FLAT_MAX_ZOOM = 8;
const FLAT_DEFAULT_POSITION = { coordinates: [0, 20] as [number, number], zoom: 1 };

// A rotating sphere, not a projection name: [longitude, latitude, roll]. The default frames
// Europe/Africa/the Atlantic, the same opening view most globe UIs default to.
type Rotation = [number, number, number];
const GLOBE_DEFAULT_ROTATION: Rotation = [-10, -15, 0];
const GLOBE_MIN_SCALE = 220;
const GLOBE_MAX_SCALE = 640;
const GLOBE_DEFAULT_SCALE = 300;
// Degrees of longitude per pixel of drag — tuned so a full-width drag turns the globe about
// three-quarters of the way around, which reads as "grabbing" it rather than nudging it.
const DRAG_SENSITIVITY = 0.28;
const AUTO_ROTATE_DEG_PER_SEC = 4;
const IDLE_MS_BEFORE_AUTOROTATE = 2600;
// A pointer that moved less than this between down and up was a click, not a drag — otherwise
// every attempt to spin the globe would also navigate to whatever country was under the cursor.
const DRAG_VS_CLICK_PX = 4;

type ViewMode = "globe" | "flat";

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
  // The orthographic globe's SVG path is pure floating-point math (no randomness), yet Node's SSR
  // render and the browser's own re-render of that same math can differ in the last few decimal
  // places — enough for React to flag a hydration mismatch on the sphere's clip path. Rendering the
  // globe/flat map only after mount sidesteps it: server and the client's first paint both show the
  // same static placeholder, and the real (client-only, floating-point-sensitive) map appears a tick
  // later, which is invisible in practice.
  const [mounted, setMounted] = useState(false);
  const [regionCounts, setRegionCounts] = useState<Record<string, RegionCount>>({});
  const [globalFeatureCount, setGlobalFeatureCount] = useState(0);
  const [hovered, setHovered] = useState<{ code: string; x: number; y: number } | null>(null);
  const [view, setView] = useState<ViewMode>("globe");
  const [flatPosition, setFlatPosition] = useState(FLAT_DEFAULT_POSITION);
  const [rotation, setRotation] = useState<Rotation>(GLOBE_DEFAULT_ROTATION);
  const [globeScale, setGlobeScale] = useState(GLOBE_DEFAULT_SCALE);

  // Refs, not state: these drive a per-frame animation loop and a drag gesture, neither of which
  // should ever cause React to re-render on their own (the rAF loop calls setRotation itself,
  // which is the one state update that actually needs to repaint).
  const lastInteractionRef = useRef(Date.now());
  const dragRef = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null);
  const rafRef = useRef<number | undefined>(undefined);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    fetch("/api/world/regions")
      .then((r) => (r.ok ? r.json() : { regions: [], global_feature_count: 0 }))
      .then((data: { regions: RegionCount[]; global_feature_count?: number }) => {
        const map: Record<string, RegionCount> = {};
        for (const r of data.regions || []) map[r.region] = r;
        setRegionCounts(map);
        setGlobalFeatureCount(data.global_feature_count || 0);
      })
      .catch(() => setRegionCounts({}));
  }, []);

  // The globe drifts slowly on its own — a static map is what "too flat" meant — and stops the
  // moment someone touches it, resuming a couple of seconds after they let go.
  useEffect(() => {
    if (view !== "globe") return;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      if (!dragRef.current && Date.now() - lastInteractionRef.current > IDLE_MS_BEFORE_AUTOROTATE) {
        setRotation(([lambda, phi, gamma]) => [lambda + AUTO_ROTATE_DEG_PER_SEC * dt, phi, gamma]);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current);
    };
  }, [view]);

  // react-simple-maps' own runtime accepts a ready-made d3 projection INSTANCE here (confirmed by
  // reading its source: a function value is used as-is, never invoked as a factory) — but its
  // published types model `projection` as a `(width, height, config) => GeoProjection` factory
  // instead, so TypeScript needs a cast to accept what the library actually expects at runtime.
  const projection = useMemo(
    () =>
      geoOrthographic()
        .scale(globeScale)
        .translate([WIDTH / 2, HEIGHT / 2])
        .rotate(rotation)
        .clipAngle(90) as unknown as ProjectionFunction,
    [globeScale, rotation],
  );

  const zoomBy = useCallback(
    (factor: number) => {
      if (view === "globe") {
        setGlobeScale((s) => Math.min(GLOBE_MAX_SCALE, Math.max(GLOBE_MIN_SCALE, s * factor)));
      } else {
        setFlatPosition((pos) => ({ ...pos, zoom: Math.min(FLAT_MAX_ZOOM, Math.max(FLAT_MIN_ZOOM, pos.zoom * factor)) }));
      }
    },
    [view],
  );

  const resetView = useCallback(() => {
    setRotation(GLOBE_DEFAULT_ROTATION);
    setGlobeScale(GLOBE_DEFAULT_SCALE);
    setFlatPosition(FLAT_DEFAULT_POSITION);
  }, []);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      lastInteractionRef.current = Date.now();
      if (view !== "globe") return;
      dragRef.current = { x: e.clientX, y: e.clientY, startX: e.clientX, startY: e.clientY };
      (e.target as Element).setPointerCapture?.(e.pointerId);
    },
    [view],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      lastInteractionRef.current = Date.now();
      if (hovered) setHovered((h) => (h ? { ...h, x: e.clientX, y: e.clientY } : h));
      const drag = dragRef.current;
      if (!drag) return;
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      drag.x = e.clientX;
      drag.y = e.clientY;
      // Incremental: each move nudges the CURRENT rotation by this step's own delta, rather than
      // recomputing from the gesture's start — that keeps the globe locked to the cursor exactly,
      // instead of drifting if a move event is skipped.
      setRotation(([lambda, phi, gamma]) => [
        lambda + dx * DRAG_SENSITIVITY,
        Math.max(-90, Math.min(90, phi - dy * DRAG_SENSITIVITY)),
        gamma,
      ]);
    },
    [hovered],
  );

  const endDrag = useCallback(() => {
    dragRef.current = null;
  }, []);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      if (view !== "globe") return;
      e.preventDefault();
      lastInteractionRef.current = Date.now();
      zoomBy(e.deltaY < 0 ? 1.08 : 1 / 1.08);
    },
    [view, zoomBy],
  );

  const navigateIfClick = useCallback(
    (e: React.MouseEvent, code: string) => {
      const drag = dragRef.current;
      const moved = drag ? Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) : 0;
      if (moved > DRAG_VS_CLICK_PX) return; // a drag that happened to end over a country, not a click
      router.push(`/world/region/${code}`);
    },
    [router],
  );

  if (!mounted) {
    return (
      <div
        aria-hidden="true"
        className="relative rounded-2xl overflow-hidden border border-gray-100 bg-gradient-to-b from-sky-100 via-sky-50 to-white animate-pulse"
        style={{ aspectRatio: `${WIDTH} / ${HEIGHT}`, maxHeight: 480 }}
      />
    );
  }

  return (
    <div>
    <div className="relative rounded-2xl overflow-hidden border border-gray-100 bg-gradient-to-b from-sky-100 via-sky-50 to-white shadow-[inset_0_1px_0_rgba(255,255,255,0.6)]">
      {/* Soft radial glow behind the globe so it reads as an object floating in space, not a flat tile. */}
      {view === "globe" && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-70"
          style={{ background: "radial-gradient(ellipse 60% 55% at 50% 48%, rgba(129,140,248,0.18), transparent 70%)" }}
        />
      )}

      <ComposableMap
        width={WIDTH}
        height={HEIGHT}
        projection={view === "globe" ? projection : "geoEqualEarth"}
        projectionConfig={view === "flat" ? { scale: 148 } : undefined}
        className="w-full h-auto touch-none select-none"
        style={{ maxHeight: 480, filter: view === "globe" ? "drop-shadow(0 18px 34px rgba(30,27,75,0.22))" : undefined }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
        onPointerCancel={endDrag}
        onWheel={handleWheel}
      >
        <defs>
          <radialGradient id="ocean" cx="38%" cy="32%" r="75%">
            <stop offset="0%" stopColor="#e0f2fe" />
            <stop offset="55%" stopColor="#bae6fd" />
            <stop offset="100%" stopColor="#7dd3fc" />
          </radialGradient>
        </defs>

        {view === "globe" ? (
          <>
            <Sphere id="world-sphere" fill="url(#ocean)" stroke="#0ea5e9" strokeWidth={0.6} strokeOpacity={0.35} />
            <Graticule stroke="#0ea5e9" strokeWidth={0.4} strokeOpacity={0.25} />
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
                      onClick={(e) => hasContent && alpha2 && navigateIfClick(e, alpha2)}
                      style={{
                        default: {
                          fill: fillForCount(activity),
                          stroke: "#ffffff",
                          strokeWidth: 0.5,
                          outline: "none",
                          cursor: hasContent ? "pointer" : "grab",
                          transition: "fill 150ms ease",
                        },
                        hover: {
                          fill: hasContent ? "#4c1d95" : "#94a3b8",
                          stroke: "#ffffff",
                          strokeWidth: 0.5,
                          outline: "none",
                          cursor: hasContent ? "pointer" : "grab",
                        },
                        pressed: { fill: "#3b0764", stroke: "#ffffff", strokeWidth: 0.5, outline: "none" },
                      }}
                    />
                  );
                })
              }
            </Geographies>
            <GlobeMarkers regionCounts={regionCounts} rotation={rotation} globeScale={globeScale} />
          </>
        ) : (
          <ZoomableGroup
            center={flatPosition.coordinates}
            zoom={flatPosition.zoom}
            minZoom={FLAT_MIN_ZOOM}
            maxZoom={FLAT_MAX_ZOOM}
            onMoveEnd={({ coordinates, zoom }) => setFlatPosition({ coordinates, zoom })}
          >
            <Sphere id="world-sphere-flat" fill="url(#ocean)" stroke="#bae6fd" strokeWidth={0.5} />
            <Graticule stroke="#7dd3fc" strokeWidth={0.4} strokeOpacity={0.5} />
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
                          strokeWidth: 0.5 / flatPosition.zoom,
                          outline: "none",
                          cursor: hasContent ? "pointer" : "default",
                          transition: "fill 150ms ease",
                        },
                        hover: {
                          fill: hasContent ? "#4c1d95" : "#cbd5e1",
                          stroke: "#ffffff",
                          strokeWidth: 0.5 / flatPosition.zoom,
                          outline: "none",
                          cursor: hasContent ? "pointer" : "default",
                        },
                        pressed: { fill: "#3b0764", stroke: "#ffffff", strokeWidth: 0.5 / flatPosition.zoom, outline: "none" },
                      }}
                    />
                  );
                })
              }
            </Geographies>
          </ZoomableGroup>
        )}
      </ComposableMap>

      {/* View toggle */}
      <div className="absolute top-3 left-3 flex rounded-xl border border-gray-200 bg-white/95 backdrop-blur-sm shadow-sm overflow-hidden text-xs font-semibold">
        <button
          type="button"
          onClick={() => setView("globe")}
          aria-pressed={view === "globe"}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 ${view === "globe" ? "bg-purple-600 text-white" : "text-gray-500 hover:bg-purple-50"}`}
        >
          <Globe2 className="h-3.5 w-3.5" /> Globe
        </button>
        <button
          type="button"
          onClick={() => setView("flat")}
          aria-pressed={view === "flat"}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 border-l border-gray-200 ${view === "flat" ? "bg-purple-600 text-white" : "text-gray-500 hover:bg-purple-50"}`}
        >
          <MapIcon className="h-3.5 w-3.5" /> Flat
        </button>
      </div>

      {/* Zoom controls */}
      <div className="absolute bottom-3 right-3 flex flex-col rounded-xl border border-gray-200 bg-white/95 backdrop-blur-sm shadow-sm overflow-hidden">
        <button
          type="button"
          aria-label="Zoom in"
          onClick={() => zoomBy(1.4)}
          disabled={view === "globe" ? globeScale >= GLOBE_MAX_SCALE : flatPosition.zoom >= FLAT_MAX_ZOOM}
          className="h-8 w-8 flex items-center justify-center text-gray-600 hover:bg-purple-50 hover:text-purple-600 disabled:opacity-30 disabled:hover:bg-transparent border-b border-gray-100"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() => zoomBy(1 / 1.4)}
          disabled={view === "globe" ? globeScale <= GLOBE_MIN_SCALE : flatPosition.zoom <= FLAT_MIN_ZOOM}
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

      {view === "globe" && (
        <p className="absolute top-3 right-3 hidden sm:block rounded-lg bg-white/80 backdrop-blur-sm px-2 py-1 text-[10px] text-gray-400">
          Drag to spin · scroll to zoom
        </p>
      )}

      {Object.keys(regionCounts).length === 0 && (
        <p className="absolute inset-x-0 bottom-1/2 translate-y-1/2 text-center text-sm text-gray-400">
          No World Features published yet — check back soon.
        </p>
      )}
    </div>
    {globalFeatureCount > 0 && (
      // Species/phenomena/technologies with no single real home (see
      // determine_world_region in world_production.py) are deliberately never pinned
      // to a country here — a marker would misrepresent them as happening in one
      // place. Still real, published Features, so this points to where they
      // actually live (the category grid just below, which lists every Feature
      // unfiltered by region) instead of letting them go quietly missing from the map.
      <p className="mt-3 text-center text-xs text-gray-400">
        +{globalFeatureCount} more worldwide — not tied to one place.{" "}
        <a href="#categories" className="font-medium text-purple-600 hover:underline">
          Browse by theme
        </a>
      </p>
    )}
    </div>
  );
}

// A marker's own rendered footprint (the solid dot plus its animate-ping ring at its largest,
// Tailwind's default ping scales to 2x) — used to keep the WHOLE marker inside the sphere's edge,
// not just its mathematical center point. Padded a few px beyond the ring's exact calculated peak
// (r=5 * 2x scale = 10) so the ring never grazes the sphere's boundary at its animation peak frame.
const MARKER_VISUAL_RADIUS_PX = 18;

// How far from the view center (in radians) a point can be before it's hidden. This is NOT simply
// "just under 90°": geoOrthographic projects a point at angle θ to a radius of `scale * sin(θ)` from
// center, and sin(θ) is nearly flat near 90° (sin(87°) ≈ 0.9986) — so a angular margin that LOOKS
// generous still puts a marker's projected position within a pixel or two of the sphere's true edge,
// where its own drawn radius (MARKER_VISUAL_RADIUS_PX) sticks out past it. Confirmed live
// (2026-09-22): a first attempt at this used a 3%-of-90° margin and markers still visibly poked past
// the globe's edge during rotation. Solving `scale * sin(θ) = scale - MARKER_VISUAL_RADIUS_PX` for θ
// instead accounts for the marker's actual pixel size, so the margin is the marker's real footprint,
// not an arbitrary angle — and it naturally tightens when zoomed out (scale small) and loosens when
// zoomed in (scale large), where the same pixel radius is a smaller share of the sphere.
function visibleHemisphereRadians(scale: number): number {
  return Math.asin(Math.max(0, Math.min(1, 1 - MARKER_VISUAL_RADIUS_PX / scale)));
}

// Pulsing hotspot markers for every region with real content, positioned at that country's true
// spherical centroid (computed from the same topology the map itself draws, so a marker is never
// off by hand-maintained coordinates).
//
// react-simple-maps' <Marker> does NOT hide a coordinate that has rotated onto the far side of the
// globe — clipAngle only clips the drawn PATH of a Geography (via geoPath), and a bare projected
// point has no such clipping applied to it. Left unguarded, a marker for a country that has
// rotated out of view still gets a valid (but meaningless) [x, y] from geoOrthographic and renders
// as a stray dot sliding around the visible hemisphere as the globe turns — confirmed live
// (2026-09-22): "dots flying around" and small dots "persistent" during rotation. Fixed by
// computing each point's angular distance from the centre of the currently visible hemisphere
// (geoDistance) and only rendering markers within it — recomputed on every rotation/scale change,
// which is why this takes `rotation` and `globeScale` as props rather than reading them once.
function GlobeMarkers({
  regionCounts, rotation, globeScale,
}: { regionCounts: Record<string, RegionCount>; rotation: Rotation; globeScale: number }) {
  const [centroids, setCentroids] = useState<Record<string, [number, number]> | null>(null);

  useEffect(() => {
    // Computed once (not per render, not per rotation) from the static topology — genuinely
    // expensive to redo every frame, cheap to do exactly once.
    import("topojson-client").then(({ feature }) => {
      const topo = worldTopoJson as any;
      const collection = feature(topo, topo.objects.countries) as any;
      const map: Record<string, [number, number]> = {};
      for (const geo of collection.features) {
        const alpha2 = countries.numericToAlpha2(geo.id as string);
        if (alpha2) map[alpha2] = geoCentroid(geo) as [number, number];
      }
      setCentroids(map);
    });
  }, []);

  if (!centroids) return null;
  // The geographic point currently facing the viewer, in [lon, lat] — the inverse of .rotate().
  const viewCenter: [number, number] = [-rotation[0], -rotation[1]];
  const maxDistance = visibleHemisphereRadians(globeScale);
  return (
    <>
      {Object.entries(regionCounts)
        .filter(([, s]) => s.feature_count > 0 || s.trend_count > 0)
        .map(([code]) => {
          const coordinates = centroids[code];
          if (!coordinates || geoDistance(coordinates, viewCenter) > maxDistance) return null;
          return (
            <Marker key={code} coordinates={coordinates}>
              {/* transform-box defaults to "view-box" for SVG children, so transform-origin: center
                  resolved to the whole SVG viewport's center (400,250), not this circle's own
                  position — every ping ring scaled toward/away from the map's center instead of
                  around itself. Confirmed live: this, not marker visibility, was the real cause of
                  "dots flying around" on 2026-09-22 (the earlier visibility fix was real too, but
                  incomplete). fill-box makes "center" resolve to the circle's own geometry. */}
              <circle r={5} fill="#a855f7" fillOpacity={0.35} className="animate-ping" style={{ transformBox: "fill-box", transformOrigin: "center" }} />
              <circle r={2.2} fill="#7c3aed" stroke="#fff" strokeWidth={0.6} />
            </Marker>
          );
        })}
    </>
  );
}

"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  ComposableMap, Geographies, Geography, ZoomableGroup, Sphere, Graticule,
} from "react-simple-maps";
import type { ProjectionFunction } from "react-simple-maps";
import { geoOrthographic, geoEqualEarth, geoCentroid, geoDistance } from "d3-geo";
import { Plus, Minus, RotateCcw, Globe2, Map as MapIcon } from "lucide-react";
import countries from "i18n-iso-countries";
import enLocale from "i18n-iso-countries/langs/en.json";
import worldTopoJson from "world-atlas/countries-110m.json";
import { iconForCategory, colorForCategory, dominantCategory, CATEGORY_ICONS, CATEGORY_COLORS } from "@/lib/worldCategoryVisuals";
import { CATEGORY_LABELS } from "@/lib/worldTypes";

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

// Marker sizing/clustering targets, in actual screen pixels rather than viewBox units — the
// viewBox is a fixed 800-unit-wide coordinate space that gets scaled to fit whatever width the
// map actually renders at, so a fixed-in-units marker radius shrinks on a narrow phone exactly
// the way the whole map does. Confirmed live 2026-09-29: on a ~380px-wide phone that made a
// marker render as only ~3-4px across, too small to read its color at a glance even once the
// color itself was correct. Converting these pixel targets to viewBox units using the map's
// ACTUAL rendered width (tracked below) keeps markers a legible, near-constant size everywhere.
const TARGET_MARKER_PX = 11;
const TARGET_MARKER_PX_SELECTED = 14;
const MIN_MARKER_UNITS = 5;
const MAX_MARKER_UNITS = 20;
// Two markers whose centers would land within this many screen px of each other merge into one
// cluster badge instead of overlapping illegibly — the standard fix for "many pins, little
// screen" (small/adjacent countries in Europe, Central America, etc. at a typical phone width).
const TARGET_CLUSTER_DISTANCE_PX = 24;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

// Tracks the map's own rendered CSS width (not the browser window's) via ResizeObserver, so
// marker sizing/clustering react to the actual space available -- correct whether that's a
// narrow phone, this component embedded in a smaller column, or a wide desktop. Starts at WIDTH
// (assumes ~1:1 scale) rather than 0, so the very first render doesn't briefly show oversized
// markers before the observer's first callback fires.
// `ready` must flip from false to true AFTER the real element (carrying `ref`) has mounted --
// confirmed live 2026-09-30: this effect originally depended on `[ref]` alone, a useRef object
// whose IDENTITY never changes across renders, so it only ever ran once, on WorldMap's very
// first render -- while `mounted` was still false and the component was showing its loading
// placeholder (a different branch of JSX with no ref attached at all). `ref.current` was null,
// the effect bailed out immediately, and the ResizeObserver was never created at all -- marker
// sizing silently stayed fixed regardless of actual screen width the entire time, the exact bug
// the responsive-sizing fix was meant to close. Re-running once `ready` becomes true is what
// actually lets it find the real element.
function useContainerWidth(ref: React.RefObject<HTMLElement>, ready: boolean): number {
  const [width, setWidth] = useState(WIDTH);
  useEffect(() => {
    const el = ref.current;
    if (!ready || !el) return;
    setWidth(el.getBoundingClientRect().width || WIDTH);
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, ready]);
  return width;
}

type ViewMode = "globe" | "flat";

interface RegionCount {
  region: string;
  count: number;
  feature_count: number;
  trend_count: number;
  trend_days: number;
  categories: Record<string, number>;
}

// A handful of buckets is plenty here — World content is admin-curated one
// Feature at a time (see scripts/generate_world_feature.py), so even a
// "lot of content" region realistically means single digits for a long
// while, not hundreds.
//
// Neutral zinc, not purple: confirmed live 2026-09-29 that a purple choropleth plus violet
// "place"-category markers (13 of 17 published Features are "place" — by far the dominant
// category with real data) made the whole map read as one undifferentiated purple wash, with
// the category markers this whole feature exists for invisible against it. Country shading
// (HOW MUCH) and marker color (WHAT KIND) need genuinely different hue families to both stay
// legible regardless of which category happens to dominate.
const BUCKETS: [number, string][] = [
  [5, "#52525b"],  // zinc-600
  [2, "#a1a1aa"],  // zinc-400
  [1, "#d4d4d8"],  // zinc-300
];

function fillForCount(count: number): string {
  for (const [min, color] of BUCKETS) {
    if (count >= min) return color;
  }
  return "#e2e8f0"; // slate-200, no content
}

export default function WorldMap({
  onSelectRegion, selectedRegion,
}: { onSelectRegion?: (code: string | null) => void; selectedRegion?: string | null } = {}) {
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
  // A cluster badge (2+ regions merged for legibility) opens a small popover listing its members
  // instead of navigating/filtering directly, since a cluster itself doesn't map to one region.
  const [openCluster, setOpenCluster] = useState<{ x: number; y: number; members: { code: string; stats: RegionCount }[] } | null>(null);

  // Refs, not state: these drive a per-frame animation loop and a drag gesture, neither of which
  // should ever cause React to re-render on their own (the rAF loop calls setRotation itself,
  // which is the one state update that actually needs to repaint).
  const lastInteractionRef = useRef(Date.now());
  const dragRef = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null);
  const rafRef = useRef<number | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const containerWidthPx = useContainerWidth(containerRef, mounted);
  // px-per-viewBox-unit at the map's actual current rendered size (viewBox is always WIDTH=800
  // units wide regardless of how many CSS pixels that's stretched/shrunk to fit).
  const pxScale = containerWidthPx / WIDTH;
  const markerRadiusUnits = clamp(TARGET_MARKER_PX / pxScale, MIN_MARKER_UNITS, MAX_MARKER_UNITS);
  const markerRadiusSelectedUnits = clamp(TARGET_MARKER_PX_SELECTED / pxScale, MIN_MARKER_UNITS + 2, MAX_MARKER_UNITS + 4);
  const clusterDistanceUnits = TARGET_CLUSTER_DISTANCE_PX / pxScale;

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
  //
  // Each drift frame re-renders every country path. Confirmed 2026-10-02: with the globe on
  // screen, clicking a video card took ~3s to navigate (vs ~0.3s with the map closed) because
  // the per-frame updates starved the navigation render. So ANY pointer/key interaction on the
  // page pauses the drift, as does the map being off-screen or the tab hidden; reduced-motion
  // users get no drift at all.
  useEffect(() => {
    if (view !== "globe" || !mounted) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const markInteraction = () => { lastInteractionRef.current = Date.now(); };
    document.addEventListener("pointerdown", markInteraction, true);
    document.addEventListener("keydown", markInteraction, true);
    let onScreen = true;
    const container = containerRef.current;
    const observer = container ? new IntersectionObserver(([entry]) => { onScreen = entry.isIntersecting; }) : null;
    if (container) observer?.observe(container);
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      if (onScreen && !document.hidden && !dragRef.current && Date.now() - lastInteractionRef.current > IDLE_MS_BEFORE_AUTOROTATE) {
        setRotation(([lambda, phi, gamma]) => [lambda + AUTO_ROTATE_DEG_PER_SEC * dt, phi, gamma]);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current);
      document.removeEventListener("pointerdown", markInteraction, true);
      document.removeEventListener("keydown", markInteraction, true);
      observer?.disconnect();
    };
  }, [view, mounted]);

  // react-simple-maps' own runtime accepts a ready-made d3 projection INSTANCE here (confirmed by
  // reading its source: a function value is used as-is, never invoked as a factory) — but its
  // published types model `projection` as a `(width, height, config) => GeoProjection` factory
  // instead, so TypeScript needs a cast to accept what the library actually expects at runtime.
  // Kept as the real, callable d3 projection object (not the ProjectionFunction-typed cast
  // ComposableMap wants) so GlobeMarkers can call it directly for its own clustering math —
  // projection([lon, lat]) => [x, y] | null is real, tested d3-geo runtime behavior regardless
  // of which prop type it's assigned to.
  const projection = useMemo(
    () =>
      geoOrthographic()
        .scale(globeScale)
        .translate([WIDTH / 2, HEIGHT / 2])
        .rotate(rotation)
        .clipAngle(90),
    [globeScale, rotation],
  );
  // Matches ComposableMap's own "geoEqualEarth" + projectionConfig={{ scale: 148 }} below --
  // needed as a real object (not a projection name string) so FlatMarkers can call it directly
  // for clustering, the same way GlobeMarkers uses `projection` above.
  const flatProjection = useMemo(
    () => geoEqualEarth().scale(148).translate([WIDTH / 2, HEIGHT / 2]),
    [],
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
      // With onSelectRegion (the interactive /world explorer), clicking filters the list on the
      // SAME page in place instead of navigating away to the separate region page — clicking the
      // already-selected country clears the filter, a natural toggle.
      if (onSelectRegion) onSelectRegion(selectedRegion === code ? null : code);
      else router.push(`/world/region/${code}`);
    },
    [router, onSelectRegion, selectedRegion],
  );

  // Positioned from the real pointer event (clientX/clientY), the same way the hover tooltip
  // below already is — not from the cluster's internal SVG viewBox coordinates, which would need
  // the SVG element's own on-screen bounding rect to convert correctly. The click event's own
  // screen position is simpler and exactly as accurate.
  const handleOpenCluster = useCallback((e: React.MouseEvent, members: { code: string; stats: RegionCount }[]) => {
    setOpenCluster({ x: e.clientX, y: e.clientY, members });
  }, []);

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
    <div ref={containerRef} className="relative rounded-2xl overflow-hidden border border-gray-100 bg-gradient-to-b from-sky-100 via-sky-50 to-white shadow-[inset_0_1px_0_rgba(255,255,255,0.6)]">
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
        projection={view === "globe" ? (projection as unknown as ProjectionFunction) : "geoEqualEarth"}
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
                          stroke: alpha2 === selectedRegion ? "#fbbf24" : "#ffffff",
                          strokeWidth: alpha2 === selectedRegion ? 1.6 : 0.5,
                          outline: "none",
                          cursor: hasContent ? "pointer" : "grab",
                          transition: "fill 150ms ease",
                        },
                        hover: {
                          fill: hasContent ? "#3f3f46" : "#94a3b8",
                          stroke: alpha2 === selectedRegion ? "#fbbf24" : "#ffffff",
                          strokeWidth: alpha2 === selectedRegion ? 1.6 : 0.5,
                          outline: "none",
                          cursor: hasContent ? "pointer" : "grab",
                        },
                        pressed: { fill: "#27272a", stroke: "#ffffff", strokeWidth: 0.5, outline: "none" },
                      }}
                    />
                  );
                })
              }
            </Geographies>
            <GlobeMarkers
              regionCounts={regionCounts} rotation={rotation} globeScale={globeScale}
              selectedRegion={selectedRegion} onSelectRegion={onSelectRegion}
              onOpenCluster={handleOpenCluster} projection={projection}
              radius={markerRadiusUnits} radiusSelected={markerRadiusSelectedUnits} clusterDistanceUnits={clusterDistanceUnits}
            />
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
                      onClick={() => hasContent && alpha2 && (onSelectRegion ? onSelectRegion(selectedRegion === alpha2 ? null : alpha2) : router.push(`/world/region/${alpha2}`))}
                      style={{
                        default: {
                          fill: fillForCount(activity),
                          stroke: alpha2 === selectedRegion ? "#fbbf24" : "#ffffff",
                          strokeWidth: (alpha2 === selectedRegion ? 2.4 : 0.5) / flatPosition.zoom,
                          outline: "none",
                          cursor: hasContent ? "pointer" : "default",
                          transition: "fill 150ms ease",
                        },
                        hover: {
                          fill: hasContent ? "#3f3f46" : "#cbd5e1",
                          stroke: alpha2 === selectedRegion ? "#fbbf24" : "#ffffff",
                          strokeWidth: (alpha2 === selectedRegion ? 2.4 : 0.5) / flatPosition.zoom,
                          outline: "none",
                          cursor: hasContent ? "pointer" : "default",
                        },
                        pressed: { fill: "#27272a", stroke: "#ffffff", strokeWidth: 0.5 / flatPosition.zoom, outline: "none" },
                      }}
                    />
                  );
                })
              }
            </Geographies>
            <FlatMarkers
              regionCounts={regionCounts} selectedRegion={selectedRegion} onSelectRegion={onSelectRegion}
              onOpenCluster={handleOpenCluster} projection={(c) => flatProjection(c) as [number, number] | null}
              radius={markerRadiusUnits} radiusSelected={markerRadiusSelectedUnits}
              clusterDistanceUnits={clusterDistanceUnits} zoom={flatPosition.zoom}
            />
          </ZoomableGroup>
        )}
      </ComposableMap>

      {/* View toggle */}
      <div className="absolute top-3 left-3 flex rounded-xl border border-gray-200 bg-white/95 backdrop-blur-sm shadow-sm overflow-hidden text-xs font-semibold">
        <button
          type="button"
          onClick={() => setView("globe")}
          aria-pressed={view === "globe"}
          className={`flex min-h-[44px] items-center gap-1.5 px-3 ${view === "globe" ? "bg-purple-600 text-white" : "text-gray-500 hover:bg-purple-50"}`}
        >
          <Globe2 className="h-3.5 w-3.5" /> Globe
        </button>
        <button
          type="button"
          onClick={() => setView("flat")}
          aria-pressed={view === "flat"}
          className={`flex min-h-[44px] items-center gap-1.5 px-3 border-l border-gray-200 ${view === "flat" ? "bg-purple-600 text-white" : "text-gray-500 hover:bg-purple-50"}`}
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
          className="h-11 w-11 flex items-center justify-center text-gray-600 hover:bg-purple-50 hover:text-purple-600 disabled:opacity-30 disabled:hover:bg-transparent border-b border-gray-100"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() => zoomBy(1 / 1.4)}
          disabled={view === "globe" ? globeScale <= GLOBE_MIN_SCALE : flatPosition.zoom <= FLAT_MIN_ZOOM}
          className="h-11 w-11 flex items-center justify-center text-gray-600 hover:bg-purple-50 hover:text-purple-600 disabled:opacity-30 disabled:hover:bg-transparent border-b border-gray-100"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Reset view"
          onClick={resetView}
          className="h-11 w-11 flex items-center justify-center text-gray-600 hover:bg-purple-50 hover:text-purple-600"
        >
          <RotateCcw className="h-3 w-3" />
        </button>
      </div>

      {/* Legend — marker color/icon says WHAT KIND of content a region has (dominant category);
          country shading separately says HOW MUCH (still count-intensity purple, unrelated to
          category color, which is why it stays a plain swatch rather than picking up the
          category palette too — two different signals would blur into one if they shared color). */}
      <div className="absolute bottom-3 left-3 rounded-xl border border-gray-200 bg-white/95 backdrop-blur-sm shadow-sm px-2.5 py-2 text-[11px] text-gray-600 flex items-center gap-2.5 flex-wrap max-w-[calc(100%-1.5rem)]">
        {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
          const Icon = CATEGORY_ICONS[key];
          return (
            <span key={key} className="flex items-center gap-1" title={label}>
              <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full" style={{ background: CATEGORY_COLORS[key] }}>
                <Icon className="h-2 w-2 text-white" strokeWidth={3} />
              </span>
              <span className="hidden sm:inline">{label}</span>
            </span>
          );
        })}
      </div>

      {hovered && (
        <div
          className="fixed z-50 rounded-lg bg-gray-900 text-white text-xs font-medium px-2.5 py-1.5 pointer-events-none shadow-lg"
          style={{ left: hovered.x + 12, top: hovered.y + 12 }}
        >
          {countries.getName(hovered.code, "en") || hovered.code} — {regionCounts[hovered.code]?.feature_count || 0} feature{regionCounts[hovered.code]?.feature_count === 1 ? "" : "s"}
          {regionCounts[hovered.code]?.trend_count ? ` · ${regionCounts[hovered.code].trend_count} trend${regionCounts[hovered.code].trend_count === 1 ? "" : "s"}` : ""}
          {(() => {
            const cats = regionCounts[hovered.code]?.categories;
            const entries = cats ? Object.entries(cats).sort((a, b) => b[1] - a[1]) : [];
            if (entries.length === 0) return null;
            return (
              <div className="mt-0.5 text-gray-300 font-normal">
                {entries.map(([cat, n]) => `${CATEGORY_LABELS[cat] || cat} (${n})`).join(" · ")}
              </div>
            );
          })()}
        </div>
      )}

      {openCluster && (
        <>
          {/* Full-screen invisible layer so a tap/click anywhere outside the popover closes it —
              the standard "click outside to dismiss" pattern, needed since the popover floats
              free of the marker that opened it rather than being anchored inline. */}
          <div className="fixed inset-0 z-40" onClick={() => setOpenCluster(null)} />
          <div
            className="fixed z-50 w-56 rounded-xl border border-gray-200 bg-white shadow-lg text-sm overflow-hidden"
            style={{ left: Math.min(openCluster.x, (typeof window !== "undefined" ? window.innerWidth : 400) - 232), top: openCluster.y + 14 }}
          >
            <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
              <span className="text-xs font-semibold text-gray-500">{openCluster.members.length} regions here</span>
              <button onClick={() => setOpenCluster(null)} aria-label="Close" className="text-gray-400 hover:text-gray-700">
                ✕
              </button>
            </div>
            <ul className="max-h-56 overflow-y-auto">
              {openCluster.members.map(({ code, stats }) => {
                const category = dominantCategory(stats.categories);
                const Icon = iconForCategory(category);
                const color = colorForCategory(category);
                return (
                  <li key={code}>
                    <button
                      onClick={() => { onSelectRegion?.(selectedRegion === code ? null : code); setOpenCluster(null); }}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-gray-50"
                    >
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full" style={{ background: color }}>
                        <Icon className="h-3 w-3 text-white" strokeWidth={3} />
                      </span>
                      <span className="flex-1 truncate text-gray-700">{countries.getName(code, "en") || code}</span>
                      <span className="text-xs text-gray-400">{stats.feature_count}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        </>
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
        <a href="#categories" className="inline-flex min-h-[44px] items-center font-medium text-purple-600 hover:underline">
          Browse by theme
        </a>
      </p>
    )}
    </div>
  );
}

// A marker's own rendered footprint (the solid dot plus its animate-ping ring at its largest,
// Tailwind's default ping scales to 2x) — used to keep the WHOLE marker inside the sphere's edge,
// not just its mathematical center point. Despite the name (kept for continuity with globeScale,
// which this is compared against directly and is itself in viewBox units, not real screen
// pixels), this needs to cover the worst case now that marker radius is responsive: a very narrow
// container can clamp radiusSelected up to MAX_MARKER_UNITS + 4 = 24 units, whose ping ring peaks
// at 2x that (48) -- padded a bit further so the ring never grazes the sphere's boundary even then.
const MARKER_VISUAL_RADIUS_PX = 52;

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

// Country centroids, computed once from the static topology and shared by both the globe and
// flat marker layers (only one of which is ever mounted at a time, since view is either "globe"
// or "flat" — but sharing the hook still keeps the two from drifting into two implementations).
function useCountryCentroids(): Record<string, [number, number]> | null {
  const [centroids, setCentroids] = useState<Record<string, [number, number]> | null>(null);
  useEffect(() => {
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
  return centroids;
}

type MarkerMember = { code: string; stats: RegionCount };
type MarkerCluster = { xy: [number, number]; coordinates: [number, number]; members: MarkerMember[] };

// Groups regions whose PROJECTED screen positions land within `distanceUnits` of each other into
// one cluster — the standard fix for many map pins on a small screen (adjacent small countries in
// Europe, Central America, etc. would otherwise overlap illegibly at any phone width). Greedy/
// single-pass: each point joins the first existing cluster within range, or starts a new one;
// cheap enough to rerun every render for the realistic region counts here (see BUCKETS' own note
// on why "a lot of content" means single digits, not hundreds, for a long while).
function clusterRegions(
  regions: [string, RegionCount][],
  centroids: Record<string, [number, number]>,
  project: (coords: [number, number]) => [number, number] | null,
  distanceUnits: number,
): MarkerCluster[] {
  const clusters: MarkerCluster[] = [];
  for (const [code, stats] of regions) {
    const coordinates = centroids[code];
    if (!coordinates) continue;
    const xy = project(coordinates);
    if (!xy) continue;
    const nearby = clusters.find((c) => Math.hypot(c.xy[0] - xy[0], c.xy[1] - xy[1]) <= distanceUnits);
    if (nearby) {
      nearby.members.push({ code, stats });
      const n = nearby.members.length;
      nearby.xy = [(nearby.xy[0] * (n - 1) + xy[0]) / n, (nearby.xy[1] * (n - 1) + xy[1]) / n];
    } else {
      clusters.push({ xy, coordinates, members: [{ code, stats }] });
    }
  }
  return clusters;
}

// One region's marker (or one cluster of 2+ regions too close together to show separately): a
// pulsing ring in the DOMINANT category's color, and that category's own icon (from
// worldCategoryVisuals — the same icons CategoryGrid and FeatureCard use) so the map itself shows
// WHAT KIND of content is there, not just a uniform "something is here" dot. Positioned via a
// plain <g transform="translate(x,y)"> using an already-projected [x,y] rather than
// react-simple-maps' <Marker> (which only accepts a single geo coordinate and projects it
// internally) — needed because a cluster's position is the AVERAGE of its members' projected
// points, not any one member's own geo coordinate.
function CategoryMarker({
  members, xy, radius, radiusSelected, selected, onClick,
}: {
  members: MarkerMember[]; xy: [number, number]; radius: number; radiusSelected: number;
  selected: boolean; onClick: (e: React.MouseEvent) => void;
}) {
  const isCluster = members.length > 1;
  // A cluster's own "dominant category" is across ALL its members combined, not any single one's.
  const combined: Record<string, number> = {};
  for (const m of members) for (const [cat, n] of Object.entries(m.stats.categories || {})) combined[cat] = (combined[cat] || 0) + n;
  const category = dominantCategory(combined);
  const Icon = iconForCategory(category);
  const color = colorForCategory(category);
  const categoryCount = Object.keys(combined).length;
  const r = selected ? radiusSelected : radius;
  return (
    <g transform={`translate(${xy[0]}, ${xy[1]})`} onClick={onClick} style={{ cursor: "pointer" }}>
      {/* transform-box defaults to "view-box" for SVG children, so transform-origin: center
          resolved to the whole SVG viewport's center, not this circle's own position — every
          ping ring scaled toward/away from the map's center instead of around itself.
          fill-box makes "center" resolve to the circle's own geometry (confirmed live
          2026-09-22, see the marker-visibility fix this replaces). */}
      <circle r={r} fill={color} fillOpacity={0.35} className="animate-ping" style={{ transformBox: "fill-box", transformOrigin: "center" }} />
      <circle r={r} fill={color} stroke="#fff" strokeWidth={selected ? 1.4 : 0.9} />
      {isCluster ? (
        <text y={1} fontSize={r * 0.95} fill="#fff" textAnchor="middle" dominantBaseline="central" fontWeight={700}>
          {members.length}
        </text>
      ) : (
        // A lucide icon renders as its own <svg> — nesting it directly (valid per the SVG spec,
        // unlike wrapping it in <foreignObject> with an HTML <div>) is what actually renders
        // reliably on mobile browsers. Confirmed live 2026-09-29: foreignObject showed as a
        // broken/blank glyph on mobile Chrome, leaving only the plain colored circles visible
        // with no icon — nested <svg> has none of that HTML-in-SVG compatibility risk.
        <Icon
          x={-r * 0.55} y={-r * 0.55} width={r * 1.1} height={r * 1.1}
          color="#fff" strokeWidth={3} style={{ pointerEvents: "none" }}
        />
      )}
      {!isCluster && categoryCount > 1 && (
        <>
          <circle cx={r * 0.78} cy={-r * 0.78} r={3.2} fill="#111827" stroke="#fff" strokeWidth={0.6} />
          <text x={r * 0.78} y={-r * 0.78} fontSize={4} fill="#fff" textAnchor="middle" dominantBaseline="central" fontWeight={700}>
            {categoryCount}
          </text>
        </>
      )}
    </g>
  );
}

// Pulsing hotspot markers for every region with real content, positioned at that country's true
// spherical centroid (computed from the same topology the map itself draws, so a marker is never
// off by hand-maintained coordinates), clustered together where they'd otherwise overlap.
//
// A bare projected point has no hemisphere clipping applied to it (unlike a Geography's drawn
// path, which geoPath/clipAngle does clip) — left unguarded, a marker for a country that has
// rotated onto the far side still gets a valid (but meaningless) [x, y] from geoOrthographic and
// renders as a stray dot sliding around the visible hemisphere as the globe turns — confirmed live
// (2026-09-22): "dots flying around" and small dots "persistent" during rotation. Fixed by
// computing each point's angular distance from the centre of the currently visible hemisphere
// (geoDistance) and only clustering/rendering markers within it — recomputed on every rotation/
// scale change, which is why this takes `rotation` and `globeScale` as props rather than reading
// them once.
function GlobeMarkers({
  regionCounts, rotation, globeScale, selectedRegion, onSelectRegion, onOpenCluster,
  projection, radius, radiusSelected, clusterDistanceUnits,
}: {
  regionCounts: Record<string, RegionCount>; rotation: Rotation; globeScale: number;
  selectedRegion?: string | null; onSelectRegion?: (code: string | null) => void;
  onOpenCluster: (e: React.MouseEvent, members: MarkerMember[]) => void;
  projection: (coords: [number, number]) => [number, number] | null;
  radius: number; radiusSelected: number; clusterDistanceUnits: number;
}) {
  const centroids = useCountryCentroids();
  if (!centroids) return null;
  // The geographic point currently facing the viewer, in [lon, lat] — the inverse of .rotate().
  const viewCenter: [number, number] = [-rotation[0], -rotation[1]];
  const maxDistance = visibleHemisphereRadians(globeScale);
  // feature_count only, not trend_count -- confirmed live 2026-09-30: a marker now carries real
  // meaning (WHAT KIND of watchable content is here), unlike the plain intensity dot it replaced,
  // and showing one for a region that has raw collected trend data but zero published World
  // Features is actively misleading (a generic gray "no category" icon on dozens of countries
  // with nothing to watch, drowning out the handful that actually have content). It also broke
  // clustering: a real content region merged into a cluster with trend-only neighbors lost its
  // own icon entirely (clusters show a count, not an icon), hiding it further.
  const eligible = Object.entries(regionCounts).filter(([, s]) => s.feature_count > 0);
  const visible = eligible.filter(([code]) => {
    const c = centroids[code];
    return c && geoDistance(c, viewCenter) <= maxDistance;
  });
  const clusters = clusterRegions(visible, centroids, (coords) => {
    const xy = projection(coords as [number, number]);
    return xy ? [xy[0], xy[1]] : null;
  }, clusterDistanceUnits);
  return (
    <>
      {clusters.map((cluster) => {
        const single = cluster.members.length === 1;
        return (
          <CategoryMarker
            key={cluster.members.map((m) => m.code).join("+")}
            members={cluster.members} xy={cluster.xy} radius={radius} radiusSelected={radiusSelected}
            selected={single && selectedRegion === cluster.members[0].code}
            onClick={(e) =>
              single
                ? onSelectRegion?.(selectedRegion === cluster.members[0].code ? null : cluster.members[0].code)
                : onOpenCluster(e, cluster.members)
            }
          />
        );
      })}
    </>
  );
}

// Same marker/clustering, flat/equal-earth projection — no hemisphere clipping needed since every
// point on a flat map is always "visible" (ZoomableGroup's own viewport clipping via the SVG's
// bounds handles the rest, the same way it already does for country shapes). The cluster distance
// shrinks with the current zoom level (dividing by `zoom`) so points that were merged at the
// default zoom naturally separate into their own markers as the user zooms in — matching how they
// visually spread apart on screen, since ZoomableGroup scales this layer's own raw coordinates by
// exactly that factor.
function FlatMarkers({
  regionCounts, selectedRegion, onSelectRegion, onOpenCluster,
  projection, radius, radiusSelected, clusterDistanceUnits, zoom,
}: {
  regionCounts: Record<string, RegionCount>; selectedRegion?: string | null; onSelectRegion?: (code: string | null) => void;
  onOpenCluster: (e: React.MouseEvent, members: MarkerMember[]) => void;
  projection: (coords: [number, number]) => [number, number] | null;
  radius: number; radiusSelected: number; clusterDistanceUnits: number; zoom: number;
}) {
  const centroids = useCountryCentroids();
  if (!centroids) return null;
  // feature_count only -- see GlobeMarkers' matching filter for why.
  const eligible = Object.entries(regionCounts).filter(([, s]) => s.feature_count > 0);
  const clusters = clusterRegions(eligible, centroids, projection, clusterDistanceUnits / zoom);
  return (
    <>
      {clusters.map((cluster) => {
        const single = cluster.members.length === 1;
        return (
          <CategoryMarker
            key={cluster.members.map((m) => m.code).join("+")}
            members={cluster.members} xy={cluster.xy} radius={radius} radiusSelected={radiusSelected}
            selected={single && selectedRegion === cluster.members[0].code}
            onClick={(e) =>
              single
                ? onSelectRegion?.(selectedRegion === cluster.members[0].code ? null : cluster.members[0].code)
                : onOpenCluster(e, cluster.members)
            }
          />
        );
      })}
    </>
  );
}

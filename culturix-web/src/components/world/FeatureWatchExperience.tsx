"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ChevronDown, ExternalLink, FileText, Globe2, Play, Volume2, VolumeX, X } from "lucide-react";
import FeatureVideoPlayer from "@/components/world/FeatureVideoPlayer";
import FeatureTranscript from "@/components/world/FeatureTranscript";
import RelatedShowcaseStrip from "@/components/world/RelatedShowcaseStrip";
import ShareButton from "@/components/world/ShareButton";
import { CATEGORY_LABELS } from "@/lib/worldTypes";
import type { WorldFeature } from "@/lib/worldTypes";
import { iconForCategory, colorForCategory } from "@/lib/worldCategoryVisuals";
import { countryName, flagEmoji } from "@/lib/worldPlaces";
import { useLocale } from "@/components/i18n/LocaleProvider";

const NEXT_UP_SECONDS = 6;
const QUEUE_PAGE = 12;
const QUEUE_MAX = 15;
// Phones and iPad portrait get the full-screen snap-scroll watch mode; iPad landscape (1024)
// and desktop get the centered player with the feed beside it.
const WATCH_MODE_QUERY = "(max-width: 1023px)";

type Detail = {
  hook_line: string | null;
  transcript: string[];
  source: WorldFeature["source"];
  translation_failed: boolean;
  lang: string;
};

function useMediaQuery(query: string): boolean | null {
  const [matches, setMatches] = useState<boolean | null>(null);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const update = () => setMatches(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, [query]);
  return matches;
}

function langSuffix(extra?: string): string {
  const params = new URLSearchParams(extra);
  const lang = new URLSearchParams(window.location.search).get("lang");
  if (lang) params.set("lang", lang);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

async function fetchFeatureList(params: Record<string, string>): Promise<WorldFeature[]> {
  try {
    const res = await fetch(`/api/world/features?${new URLSearchParams({ limit: String(QUEUE_PAGE), ...params })}`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.features) ? data.features : [];
  } catch {
    return [];
  }
}

// What plays after this video: same place first, then same category, then the newest videos.
function useNextUpQueue(feature: WorldFeature): { queue: WorldFeature[]; loaded: boolean } {
  const [state, setState] = useState<{ queue: WorldFeature[]; loaded: boolean }>({ queue: [], loaded: false });
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      feature.subject_region ? fetchFeatureList({ region: feature.subject_region }) : Promise.resolve([]),
      feature.subject_category ? fetchFeatureList({ category: feature.subject_category }) : Promise.resolve([]),
      fetchFeatureList({}),
    ]).then((lists) => {
      if (cancelled) return;
      const seen = new Set([feature.id]);
      const queue: WorldFeature[] = [];
      for (const f of lists.flat()) {
        if (seen.has(f.id) || !f.final_video_url) continue;
        seen.add(f.id);
        queue.push(f);
      }
      setState({ queue: queue.slice(0, QUEUE_MAX), loaded: true });
    });
    return () => { cancelled = true; };
  }, [feature.id, feature.subject_region, feature.subject_category]);
  return state;
}

// hook_line, transcript and source only come with the detail endpoint, which also translates
// hook_line and transcript into the site language (the existing Google-backed translation).
function useFeatureDetails(feature: WorldFeature, locale: string) {
  const [cache, setCache] = useState<Record<string, Detail>>(() => ({
    [`${feature.id}:en`]: {
      hook_line: feature.hook_line ?? null,
      transcript: feature.transcript || [],
      source: feature.source ?? null,
      translation_failed: false,
      lang: "en",
    },
  }));
  const inFlight = useRef(new Set<string>());

  const request = useCallback((id: string) => {
    const key = `${id}:${locale}`;
    if (cache[key] || inFlight.current.has(key)) return;
    inFlight.current.add(key);
    fetch(`/api/world/features/${id}?lang=${encodeURIComponent(locale)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;
        setCache((c) => ({
          ...c,
          [key]: {
            hook_line: data.hook_line ?? null,
            transcript: Array.isArray(data.transcript) ? data.transcript : [],
            source: data.source ?? null,
            translation_failed: Boolean(data.translation_failed),
            lang: data.transcript_language || locale,
          },
        }));
      })
      .catch(() => {})
      .finally(() => inFlight.current.delete(key));
  }, [cache, locale]);

  const get = useCallback(
    (id: string): Detail | undefined => cache[`${id}:${locale}`] ?? cache[`${id}:en`],
    [cache, locale],
  );
  return { get, request };
}

function useGoBack() {
  const router = useRouter();
  return useCallback((e: React.MouseEvent) => {
    let cameFromSite = false;
    try { cameFromSite = new URL(document.referrer).origin === window.location.origin; } catch { /* no referrer */ }
    if (cameFromSite && window.history.length > 1) {
      e.preventDefault();
      router.back();
    }
  }, [router]);
}

function PlaceChip({ code, dark = false }: { code: string | null; dark?: boolean }) {
  const { locale, messages } = useLocale();
  const name = countryName(code, locale);
  const cls = dark
    ? "bg-white/15 text-white hover:bg-white/25"
    : "bg-gray-100 text-gray-700 hover:bg-gray-200";
  if (!code || !name) {
    return (
      <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${cls}`}>
        <Globe2 className="h-3 w-3" aria-hidden="true" /> {messages.world.worldwide}
      </span>
    );
  }
  return (
    <Link
      href={`/world?region=${code}`}
      // The ::before pad gives the small chip a 44px-tall touch area without changing its look.
      className={`relative inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-400 before:absolute before:inset-x-0 before:-inset-y-2.5 before:content-[''] ${cls}`}
    >
      <span aria-hidden="true">{flagEmoji(code)}</span> {name}
    </Link>
  );
}

function CategoryChip({ category, dark = false }: { category: string | null; dark?: boolean }) {
  const { messages } = useLocale();
  if (!category) return null;
  const Icon = iconForCategory(category);
  const color = colorForCategory(category);
  const label = messages.world.categories[category] || CATEGORY_LABELS[category] || category;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold"
      style={dark ? { background: color, color: "#fff" } : { background: `${color}1a`, color }}
    >
      <Icon className="h-3 w-3" aria-hidden="true" /> {label}
    </span>
  );
}

export default function FeatureWatchExperience({ feature, autoplay = false }: { feature: WorldFeature; autoplay?: boolean }) {
  const { locale } = useLocale();
  const watchMode = useMediaQuery(WATCH_MODE_QUERY);
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)") === true;
  const { queue, loaded } = useNextUpQueue(feature);
  const details = useFeatureDetails(feature, locale);
  const title = feature.title || feature.subject_text || "";

  // Before mount the layout isn't known yet: render the same static, text-first block on the
  // server and on the client's first paint (real title/hook for SEO, no video element yet).
  if (watchMode === null) {
    return (
      <div className="py-10 max-w-2xl mx-auto">
        <div className="mx-auto aspect-[9/16] w-full max-w-xs rounded-2xl bg-gray-900 overflow-hidden">
          {feature.thumbnail_url && (
            // eslint-disable-next-line @next/next/no-img-element -- external source image
            <img src={feature.thumbnail_url} alt="" className="h-full w-full object-cover" />
          )}
        </div>
        <h1 className="mt-6 text-2xl font-bold text-gray-900">{title}</h1>
        {feature.hook_line && <p className="mt-2 text-gray-500">{feature.hook_line}</p>}
      </div>
    );
  }

  return watchMode ? (
    <WatchMode feature={feature} queue={queue} loaded={loaded} details={details} reducedMotion={reducedMotion} />
  ) : (
    <DesktopWatch feature={feature} queue={queue} details={details} reducedMotion={reducedMotion} autoplay={autoplay} />
  );
}

type DetailsApi = ReturnType<typeof useFeatureDetails>;

function DetailsPanel({ feature, detail }: { feature: WorldFeature; detail: Detail | undefined }) {
  const { messages } = useLocale();
  const t = messages.world;
  const englishTranscript = feature.transcript || [];
  const lines = detail?.transcript ?? englishTranscript;
  return (
    <>
      {detail?.source && (
        <p className="text-sm text-gray-600">
          {t.source}:{" "}
          <a href={detail.source.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-purple-700 hover:underline">
            {detail.source.label} <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        </p>
      )}
      <FeatureTranscript
        key={`${feature.id}:${detail ? detail.lang : "pending"}`}
        featureId={feature.id}
        initial={detail?.lang === "en" || !detail ? lines : englishTranscript}
        initialLang={detail?.lang ?? "en"}
        initialLines={lines}
        initialFailed={detail?.translation_failed ?? false}
      />
    </>
  );
}

function DesktopWatch({
  feature, queue, details, reducedMotion, autoplay,
}: {
  feature: WorldFeature; queue: WorldFeature[]; details: DetailsApi; reducedMotion: boolean; autoplay: boolean;
}) {
  const router = useRouter();
  const { messages } = useLocale();
  const t = messages.world;
  const goBack = useGoBack();
  const { request: requestDetail } = details;
  const [phase, setPhase] = useState<"idle" | "counting" | "cancelled" | "manual">("idle");
  const [secondsLeft, setSecondsLeft] = useState(NEXT_UP_SECONDS);
  const next = queue[0];
  const detail = details.get(feature.id);
  const title = feature.title || feature.subject_text || "";

  useEffect(() => { requestDetail(feature.id); }, [requestDetail, feature.id]);

  const playNext = useCallback(() => {
    if (next) router.push(`/world/feature/${next.id}${langSuffix("autoplay=1")}`);
  }, [next, router]);

  useEffect(() => {
    if (phase !== "counting") return;
    if (secondsLeft <= 0) { playNext(); return; }
    const id = setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(id);
  }, [phase, secondsLeft, playNext]);

  const onEnded = useCallback(() => {
    if (!next) return;
    setSecondsLeft(NEXT_UP_SECONDS);
    setPhase(reducedMotion ? "manual" : "counting");
  }, [next, reducedMotion]);

  return (
    <div className="py-6 lg:py-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0">
        <Link
          href="/world"
          onClick={goBack}
          className="inline-flex min-h-[44px] items-center gap-1.5 text-sm text-gray-500 hover:text-purple-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 rounded"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> {t.back}
        </Link>

        <div className="mt-2 mx-auto aspect-[9/16] rounded-2xl overflow-hidden bg-black" style={{ height: "min(68vh, 720px)" }}>
          {feature.final_video_url && (
            <FeatureVideoPlayer
              src={feature.final_video_url}
              thumbnailUrl={feature.thumbnail_url}
              autoPlay={autoplay && !reducedMotion}
              onEnded={onEnded}
              label={title}
            />
          )}
        </div>

        <div className="mx-auto max-w-2xl">
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <CategoryChip category={feature.subject_category} />
            <PlaceChip code={feature.subject_region} />
          </div>
          <div className="mt-3 flex items-start justify-between gap-4">
            <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
            <ShareButton path={`/world/feature/${feature.id}`} title={title} />
          </div>
          {detail?.hook_line && <p className="mt-2 text-gray-600 leading-relaxed">{detail.hook_line}</p>}

          <details className="group mt-6 rounded-2xl border border-gray-100 bg-white">
            <summary className="flex min-h-[44px] cursor-pointer list-none items-center justify-between gap-2 rounded-2xl px-4 py-2 text-sm font-semibold text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 [&::-webkit-details-marker]:hidden">
              <span className="flex items-center gap-2"><FileText className="h-4 w-4 text-purple-600" aria-hidden="true" /> {t.details}</span>
              <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
            </summary>
            <div className="px-4 pb-4">
              <DetailsPanel feature={feature} detail={detail} />
            </div>
          </details>

          {/* Capped at two clips so the page never mounts more than three <video> elements. */}
          <RelatedShowcaseStrip toons={feature.related_toons?.slice(0, 2)} />
        </div>
      </div>

      <aside className="lg:sticky lg:top-20 lg:self-start space-y-6" aria-label={t.moreToWatch}>
        {next && (
          <section aria-live="polite" className="rounded-2xl border border-purple-100 bg-purple-50/40 p-3">
            <h2 className="px-1 pb-2 text-xs font-semibold uppercase tracking-wide text-purple-700">{t.nextUp}</h2>
            <QueueRow feature={next} large />
            {phase === "counting" && (
              <div className="mt-3 flex items-center justify-between gap-2 px-1">
                <span className="text-sm text-gray-700">{t.playingIn} {secondsLeft}{t.seconds}</span>
                <div className="flex gap-2">
                  <button type="button" onClick={() => setPhase("cancelled")} className="min-h-[44px] rounded-xl border border-gray-200 bg-white px-3 text-sm font-semibold text-gray-700 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500">
                    {t.cancel}
                  </button>
                  <button type="button" onClick={playNext} className="min-h-[44px] rounded-xl bg-purple-600 px-3 text-sm font-semibold text-white hover:bg-purple-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 focus-visible:ring-offset-2">
                    {t.playNow}
                  </button>
                </div>
              </div>
            )}
            {(phase === "cancelled" || phase === "manual") && (
              <div className="mt-3 flex items-center justify-between gap-2 px-1">
                <span className="text-sm text-gray-600">{t.autoplayOff}</span>
                <button type="button" onClick={playNext} className="min-h-[44px] rounded-xl bg-purple-600 px-3 text-sm font-semibold text-white hover:bg-purple-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 focus-visible:ring-offset-2">
                  {t.playNow}
                </button>
              </div>
            )}
          </section>
        )}

        {queue.length > 1 && (
          <section>
            <h2 className="px-1 pb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{t.moreToWatch}</h2>
            <ul className="space-y-2">
              {queue.slice(1, 9).map((f) => (
                <li key={f.id}><QueueRow feature={f} /></li>
              ))}
            </ul>
          </section>
        )}
      </aside>
    </div>
  );
}

function QueueRow({ feature, large = false }: { feature: WorldFeature; large?: boolean }) {
  const { locale, messages } = useLocale();
  const name = countryName(feature.subject_region, locale);
  return (
    <Link
      href={`/world/feature/${feature.id}`}
      className="group flex items-center gap-3 rounded-xl p-1 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
    >
      <div className={`relative shrink-0 overflow-hidden rounded-lg bg-gray-900 aspect-[9/16] ${large ? "w-20" : "w-14"}`}>
        {feature.thumbnail_url && (
          // eslint-disable-next-line @next/next/no-img-element -- external source image
          <img src={feature.thumbnail_url} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover" />
        )}
        <span className="absolute inset-0 flex items-center justify-center" aria-hidden="true">
          <Play className="h-4 w-4 text-white drop-shadow" fill="currentColor" />
        </span>
      </div>
      <div className="min-w-0">
        <p className={`font-semibold text-gray-900 leading-snug line-clamp-2 group-hover:text-purple-700 ${large ? "text-sm" : "text-[13px]"}`}>
          {feature.title || feature.subject_text}
        </p>
        <p className="mt-1 text-xs text-gray-500 truncate">
          {name ? <><span aria-hidden="true">{flagEmoji(feature.subject_region)}</span> {name}</> : messages.world.worldwide}
        </p>
      </div>
    </Link>
  );
}

function WatchMode({
  feature, queue, loaded, details, reducedMotion,
}: {
  feature: WorldFeature; queue: WorldFeature[]; loaded: boolean; details: DetailsApi; reducedMotion: boolean;
}) {
  const { messages } = useLocale();
  const t = messages.world;
  const goBack = useGoBack();
  const items = [feature, ...queue];
  const [active, setActive] = useState(0);
  const [muted, setMuted] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const slotRefs = useRef<(HTMLElement | null)[]>([]);
  const videoRefs = useRef(new Map<number, HTMLVideoElement>());
  const activeItem = items[active] ?? feature;
  const activeDetail = details.get(activeItem.id);

  // Full-screen layer over the page: lock the page behind it.
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.style.overflow;
    root.style.overflow = "hidden";
    scrollerRef.current?.focus({ preventScroll: true });
    return () => { root.style.overflow = previous; };
  }, []);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && entry.intersectionRatio >= 0.6) {
            const index = Number((entry.target as HTMLElement).dataset.index);
            if (!Number.isNaN(index)) setActive(index);
          }
        }
      },
      { root: scroller, threshold: [0.6] },
    );
    slotRefs.current.forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [items.length]);

  // A new video always starts muted: sound only ever follows an explicit tap.
  useEffect(() => {
    setMuted(true);
    setDrawerOpen(false);
  }, [active]);

  useEffect(() => {
    videoRefs.current.forEach((video, index) => {
      if (index === active) {
        video.muted = true;
        if (!reducedMotion) video.play().catch(() => setPlaying(false));
      } else {
        video.pause();
      }
    });
  }, [active, reducedMotion]);

  const { request: requestDetail } = details;
  useEffect(() => {
    requestDetail(activeItem.id);
  }, [requestDetail, activeItem.id]);

  // Keep the address bar on the video being watched (share/refresh land on it) without a
  // navigation, which would re-render the page and tear down the scroller.
  useEffect(() => {
    const url = `/world/feature/${activeItem.id}${langSuffix()}`;
    if (window.location.pathname + window.location.search !== url) {
      window.history.replaceState(window.history.state, "", url);
    }
  }, [activeItem.id]);

  const toggleMute = useCallback(() => {
    const video = videoRefs.current.get(active);
    const nextMuted = !muted;
    setMuted(nextMuted);
    if (video) {
      video.muted = nextMuted;
      if (!nextMuted && video.paused) video.play().catch(() => {});
    }
  }, [active, muted]);

  // Tap: first unmute (inside the gesture, which iOS requires for sound), then play/pause.
  const onTap = useCallback(() => {
    const video = videoRefs.current.get(active);
    if (!video) return;
    if (muted && !video.paused) { toggleMute(); return; }
    if (video.paused) video.play().catch(() => {});
    else video.pause();
  }, [active, muted, toggleMute]);

  const onEnded = useCallback((index: number) => {
    if (index !== active || reducedMotion) return;
    slotRefs.current[index + 1]?.scrollIntoView({ behavior: "smooth" });
  }, [active, reducedMotion]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawerOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  return (
    <div role="dialog" aria-modal="true" aria-label={activeItem.title || activeItem.subject_text || t.watch} className="fixed inset-0 z-[60] bg-black text-white">
      <div
        ref={scrollerRef}
        tabIndex={0}
        className="h-full w-full overflow-y-auto overscroll-contain snap-y snap-mandatory focus:outline-none [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {items.map((item, index) => {
          const near = Math.abs(index - active) <= 1;
          const isActive = index === active;
          const detail = details.get(item.id);
          const itemTitle = item.title || item.subject_text || "";
          return (
            <section
              key={item.id}
              data-index={index}
              ref={(el) => { slotRefs.current[index] = el; }}
              aria-label={itemTitle}
              className="relative flex h-[100dvh] w-full snap-start snap-always items-center justify-center overflow-hidden"
            >
              <div className="relative h-full w-full max-w-[calc(100dvh*9/16)] bg-black">
                {near && item.final_video_url ? (
                  <video
                    ref={(el) => { if (el) videoRefs.current.set(index, el); else videoRefs.current.delete(index); }}
                    src={item.final_video_url}
                    poster={item.thumbnail_url || undefined}
                    muted
                    playsInline
                    preload={isActive || index === active + 1 ? "auto" : "metadata"}
                    aria-label={itemTitle}
                    className="h-full w-full object-cover"
                    onPlay={() => isActive && setPlaying(true)}
                    onPause={() => isActive && setPlaying(false)}
                    onEnded={() => onEnded(index)}
                  />
                ) : item.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element -- external source image
                  <img src={item.thumbnail_url} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover opacity-70" />
                ) : null}

                <button
                  type="button"
                  onClick={onTap}
                  tabIndex={isActive ? 0 : -1}
                  aria-label={muted && playing ? t.tapToUnmute : playing ? t.pause : t.play}
                  className="absolute inset-0 z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-purple-400"
                />

                {isActive && !playing && (
                  <span className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center" aria-hidden="true">
                    <span className="flex h-16 w-16 items-center justify-center rounded-full bg-black/50 ring-1 ring-white/40">
                      <Play className="h-7 w-7 translate-x-0.5" fill="currentColor" />
                    </span>
                  </span>
                )}

                {isActive && muted && playing && (
                  <span className="pointer-events-none absolute left-1/2 top-16 z-10 -translate-x-1/2 inline-flex items-center gap-1.5 rounded-full bg-black/55 px-3 py-1.5 text-xs font-semibold" aria-hidden="true">
                    <VolumeX className="h-3.5 w-3.5" /> {t.tapToUnmute}
                  </span>
                )}

                <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-black/85 via-black/40 to-transparent px-4 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-24">
                  <div className="flex items-end gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="pointer-events-auto flex flex-wrap items-center gap-2">
                        <CategoryChip category={item.subject_category} dark />
                        <PlaceChip code={item.subject_region} dark />
                      </div>
                      <h2 className="mt-2 text-lg font-bold leading-snug line-clamp-2">{itemTitle}</h2>
                      {detail?.hook_line && <p className="mt-1 text-sm text-white/85 leading-snug line-clamp-3">{detail.hook_line}</p>}
                      {detail?.source && (
                        <a
                          href={detail.source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          tabIndex={isActive ? 0 : -1}
                          className="pointer-events-auto mt-1.5 inline-flex min-h-[44px] items-center gap-1 text-xs text-white/75 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-400 rounded"
                        >
                          {t.source}: {detail.source.label} <ExternalLink className="h-3 w-3" aria-hidden="true" />
                        </a>
                      )}
                      {index === 0 && active === 0 && items.length > 1 && (
                        <p className="mt-2 text-[11px] text-white/60">{t.swipeHint}</p>
                      )}
                    </div>
                    {isActive && (
                      <div className="pointer-events-auto flex shrink-0 flex-col items-center gap-3">
                        <button
                          type="button"
                          onClick={toggleMute}
                          aria-label={muted ? t.unmute : t.mute}
                          aria-pressed={!muted}
                          className="flex h-11 w-11 items-center justify-center rounded-full bg-black/40 backdrop-blur-sm hover:bg-black/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-400"
                        >
                          {muted ? <VolumeX className="h-5 w-5" aria-hidden="true" /> : <Volume2 className="h-5 w-5" aria-hidden="true" />}
                        </button>
                        <ShareButton path={`/world/feature/${item.id}`} title={itemTitle} variant="dark" compact />
                        <button
                          type="button"
                          onClick={() => setDrawerOpen(true)}
                          aria-label={t.details}
                          aria-expanded={drawerOpen}
                          className="flex h-11 w-11 items-center justify-center rounded-full bg-black/40 backdrop-blur-sm hover:bg-black/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-400"
                        >
                          <FileText className="h-5 w-5" aria-hidden="true" />
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </section>
          );
        })}

        {loaded && (
          <section className="flex h-[100dvh] w-full snap-start flex-col items-center justify-center gap-4 px-6 text-center">
            <p className="text-base font-semibold">{t.endOfFeed}</p>
            <Link href="/world" className="inline-flex min-h-[44px] items-center rounded-xl bg-white px-5 text-sm font-semibold text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-400">
              {t.title}
            </Link>
          </section>
        )}
      </div>

      <Link
        href="/world"
        onClick={goBack}
        aria-label={t.back}
        className="absolute left-3 top-[max(0.75rem,env(safe-area-inset-top))] z-30 flex h-11 w-11 items-center justify-center rounded-full bg-black/40 backdrop-blur-sm hover:bg-black/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-400"
      >
        <ArrowLeft className="h-5 w-5" aria-hidden="true" />
      </Link>

      {drawerOpen && (
        <>
          <div className="absolute inset-0 z-40 bg-black/50" onClick={() => setDrawerOpen(false)} aria-hidden="true" />
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t.details}
            className="absolute inset-x-0 bottom-0 z-50 max-h-[75dvh] overflow-y-auto rounded-t-2xl bg-white px-4 pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-3 text-gray-900"
          >
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">{t.details}</h2>
              <button
                type="button"
                onClick={() => setDrawerOpen(false)}
                aria-label={t.cancel}
                autoFocus
                className="flex h-11 w-11 items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
            <DetailsPanel feature={activeItem} detail={activeDetail} />
          </div>
        </>
      )}
    </div>
  );
}

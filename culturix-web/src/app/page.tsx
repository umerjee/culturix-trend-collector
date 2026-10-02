import Link from "next/link";
import { cookies } from "next/headers";
import { ArrowRight, CheckCircle, Database, ShieldCheck, UserCheck, Globe2, Play, ChevronDown, MapPin } from "lucide-react";
import { buttonVariants } from "@/components/ui/Button";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";
import FeatureCard from "@/components/world/FeatureCard";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import { CATEGORY_LABELS } from "@/lib/worldTypes";
import type { WorldFeature } from "@/lib/worldTypes";
import { CATEGORY_ICONS, CATEGORY_COLORS, iconForCategory, colorForCategory } from "@/lib/worldCategoryVisuals";
import { countryName, flagEmoji } from "@/lib/worldPlaces";
import { homeCopy, homeLocale } from "@/content/homeCopy";

export const metadata = { alternates: { canonical: "/" } };

const LATEST_COUNT = 8;
const SOURCES = ["Wikipedia", "UNESCO World Heritage"];
const STEP_ICONS = [Database, ShieldCheck, UserCheck];

// The newest published videos, from the same endpoint the feed uses. Cached for 10 minutes;
// on any failure the page simply omits the video sections rather than showing placeholders.
async function getLatest(): Promise<{ features: WorldFeature[]; total: number } | null> {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/features?limit=${LATEST_COUNT + 1}&offset=0`, {
      next: { revalidate: 600 },
      signal: AbortSignal.timeout(6000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const features: WorldFeature[] = Array.isArray(data.features) ? data.features : [];
    return { features, total: typeof data.total === "number" ? data.total : features.length };
  } catch {
    return null;
  }
}

async function getCountriesWithVideos(): Promise<number | null> {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/regions`, {
      next: { revalidate: 600 },
      signal: AbortSignal.timeout(6000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const regions: { feature_count?: number }[] = Array.isArray(data?.regions) ? data.regions : [];
    return regions.filter((r) => (r.feature_count ?? 0) > 0).length;
  } catch {
    return null;
  }
}

export default async function LandingPage({ searchParams }: { searchParams: { lang?: string } }) {
  const locale = homeLocale(searchParams.lang || cookies().get("culturix_language")?.value);
  const t = homeCopy(locale);
  const [latest, countries] = await Promise.all([getLatest(), getCountriesWithVideos()]);

  const featured = latest?.features.find((f) => f.thumbnail_url) ?? null;
  const grid = (latest?.features ?? []).filter((f) => f.id !== featured?.id).slice(0, LATEST_COUNT);

  // Only real numbers: a failed fetch drops its stat instead of showing a guess.
  const stats: { val: string; label: string }[] = [
    ...(latest && latest.total > 0 ? [{ val: String(latest.total), label: t.stats.videos }] : []),
    ...(countries ? [{ val: String(countries), label: t.stats.countries }] : []),
    { val: String(Object.keys(CATEGORY_LABELS).length), label: t.stats.themes },
    { val: t.stats.free, label: t.stats.freeLabel },
  ];

  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: t.faq.items.map((item) => ({
      "@type": "Question",
      name: item.q,
      acceptedAnswer: { "@type": "Answer", text: item.a },
    })),
  };

  return (
    <div lang={locale} className="min-h-screen bg-white overflow-x-hidden">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }} />
      <MarketingHeader transparent />

      {/* Hero */}
      <section className="pt-24 pb-14 sm:pt-32 sm:pb-20 px-4 sm:px-6 bg-slate-950 relative overflow-hidden">
        <div className="absolute inset-0 pointer-events-none" aria-hidden="true">
          <div className="absolute top-1/4 left-1/3 w-72 h-72 sm:w-96 sm:h-96 bg-indigo-600/20 rounded-full blur-3xl" />
          <div className="absolute bottom-0 right-1/4 w-64 h-64 sm:w-80 sm:h-80 bg-purple-600/15 rounded-full blur-3xl" />
        </div>

        <div className={`max-w-6xl mx-auto relative grid gap-10 lg:gap-14 items-center ${featured ? "lg:grid-cols-[1.25fr_1fr]" : ""}`}>
          <div className={featured ? "" : "max-w-2xl mx-auto text-center"}>
            <div className="inline-flex items-center gap-2 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs font-semibold px-3 py-1.5 mb-5 sm:mb-6">
              <Globe2 className="h-3.5 w-3.5" aria-hidden="true" />
              {t.hero.badge}
            </div>
            <h1 className="text-3xl min-[400px]:text-4xl sm:text-5xl font-extrabold text-white leading-tight mb-5 sm:mb-6">
              {t.hero.title}{" "}
              <span className="bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                {t.hero.titleAccent}
              </span>
            </h1>
            <p className="text-base sm:text-lg text-gray-300 mb-7 sm:mb-8 leading-relaxed">{t.hero.body}</p>

            <div className={`flex flex-col sm:flex-row gap-3 ${featured ? "" : "sm:justify-center"}`}>
              <Link href="/world" className={`${buttonVariants({ variant: "primary", size: "lg" })} px-6 sm:px-8`}>
                {t.hero.ctaPrimary} <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
              <Link
                href="#how-it-works"
                className="inline-flex min-h-[44px] items-center justify-center gap-2 bg-white/5 border border-white/10 text-gray-200 font-semibold px-6 sm:px-8 py-4 rounded-xl hover:bg-white/10 transition-colors text-base"
              >
                {t.hero.ctaSecondary}
              </Link>
            </div>
            <p className="mt-4 text-sm text-gray-400">{t.hero.note}</p>
          </div>

          {featured && <FeaturedVideo feature={featured} label={t.hero.latest} categoryName={featured.subject_category ? t.themes.items[featured.subject_category]?.name : null} locale={locale} />}
        </div>
      </section>

      {/* Stats */}
      <section className="py-8 sm:py-10 border-b border-gray-100 bg-white">
        <dl className={`max-w-4xl mx-auto px-4 sm:px-6 grid grid-cols-2 gap-x-4 gap-y-6 text-center ${stats.length >= 4 ? "md:grid-cols-4" : "md:grid-cols-3"}`}>
          {stats.map((s) => (
            <div key={s.label} className="flex flex-col-reverse">
              <dt className="text-xs sm:text-sm text-gray-500 mt-1">{s.label}</dt>
              <dd className="text-2xl sm:text-3xl font-extrabold text-indigo-600">{s.val}</dd>
            </div>
          ))}
        </dl>
      </section>

      {/* Latest videos */}
      {grid.length > 0 && (
        <section id="latest" className="py-14 sm:py-20 px-4 sm:px-6 scroll-mt-16">
          <div className="max-w-6xl mx-auto">
            <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
              <div>
                <h2 className="text-2xl sm:text-3xl font-bold text-gray-900">{t.latest.title}</h2>
                <p className="mt-2 text-gray-500">{t.latest.body}</p>
              </div>
              <Link href="/world" className="hidden sm:inline-flex min-h-[44px] items-center gap-1.5 text-sm font-semibold text-indigo-600 hover:text-indigo-700">
                {t.latest.seeAll} <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
            <ul className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-5">
              {grid.map((f, i) => (
                // Phones get a shorter strip (4); the full feed is one tap away.
                <li key={f.id} className={i >= 4 ? "hidden sm:block" : ""}>
                  <FeatureCard feature={f} />
                </li>
              ))}
            </ul>
            <div className="mt-8 text-center">
              <Link href="/world" className={`${buttonVariants({ variant: "primary", size: "lg" })} w-full sm:w-auto`}>
                {t.latest.seeAll} <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
          </div>
        </section>
      )}

      {/* Themes */}
      <section id="themes" className="py-14 sm:py-20 px-4 sm:px-6 bg-gray-50 scroll-mt-16">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10">
            <h2 className="text-2xl sm:text-3xl font-bold text-gray-900 mb-3">{t.themes.title}</h2>
            <p className="text-gray-500 max-w-2xl mx-auto">{t.themes.body}</p>
          </div>
          <ul className="grid grid-cols-2 md:grid-cols-3 gap-3 sm:gap-4">
            {Object.keys(CATEGORY_LABELS).map((key) => {
              const Icon = CATEGORY_ICONS[key];
              const color = CATEGORY_COLORS[key];
              const item = t.themes.items[key];
              return (
                <li key={key}>
                  <Link
                    href={`/world?category=${key}`}
                    className="group flex h-full flex-col rounded-2xl border border-gray-100 bg-white p-4 sm:p-5 transition hover:border-indigo-200 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                  >
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ background: `${color}1a` }} aria-hidden="true">
                      <Icon className="h-5 w-5" style={{ color }} />
                    </span>
                    <span className="mt-3 font-semibold text-gray-900 group-hover:text-indigo-700">{item.name}</span>
                    <span className="mt-1 text-sm text-gray-500 leading-snug">{item.desc}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
          <div className="mt-8 text-center">
            <Link href="/world" className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-gray-200 bg-white px-5 text-sm font-semibold text-gray-800 hover:bg-gray-50">
              <MapPin className="h-4 w-4 text-indigo-500" aria-hidden="true" /> {t.themes.byPlace}
            </Link>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-14 sm:py-20 px-4 sm:px-6 scroll-mt-16">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10 sm:mb-14">
            <p className="text-xs font-semibold text-indigo-600 uppercase tracking-wide mb-3">{t.how.eyebrow}</p>
            <h2 className="text-2xl sm:text-4xl font-bold text-gray-900 mb-4">{t.how.title}</h2>
            <p className="text-gray-500 max-w-xl mx-auto">{t.how.body}</p>
          </div>
          <ol className="grid md:grid-cols-3 gap-4 sm:gap-6">
            {t.how.steps.map((s, i) => {
              const Icon = STEP_ICONS[i];
              return (
                <li key={s.title} className="rounded-2xl border border-gray-100 p-5 sm:p-6">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="h-10 w-10 rounded-xl bg-indigo-50 flex items-center justify-center" aria-hidden="true">
                      <Icon className="h-5 w-5 text-indigo-500" />
                    </div>
                    <span className="text-xs font-bold text-gray-400">0{i + 1}</span>
                  </div>
                  <h3 className="font-semibold text-gray-900 mb-2">{s.title}</h3>
                  <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
                </li>
              );
            })}
          </ol>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
            <span className="text-xs text-gray-500 mr-1">{t.how.sourcesLabel}</span>
            {SOURCES.map((name) => (
              <span key={name} className="text-xs font-medium rounded-full bg-gray-50 border border-gray-100 text-gray-600 px-3 py-1.5">{name}</span>
            ))}
          </div>
        </div>
      </section>

      {/* Trust */}
      <section id="about" className="py-14 sm:py-20 px-4 sm:px-6 bg-slate-950 scroll-mt-16">
        <div className="max-w-4xl mx-auto grid md:grid-cols-2 gap-8 md:gap-12 items-center">
          <div>
            <p className="inline-flex items-center gap-2 text-emerald-300 text-xs font-semibold uppercase tracking-wide mb-4">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" /> {t.trust.eyebrow}
            </p>
            <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4">{t.trust.title}</h2>
            <p className="text-gray-300 leading-relaxed">{t.trust.body}</p>
          </div>
          <ul className="space-y-3">
            {t.trust.points.map((point) => (
              <li key={point} className="flex items-start gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3.5 text-sm sm:text-base text-gray-200">
                <CheckCircle className="h-5 w-5 shrink-0 text-emerald-400 mt-0.5" aria-hidden="true" />
                {point}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="py-14 sm:py-20 px-4 sm:px-6 scroll-mt-16">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-2xl sm:text-3xl font-bold text-center text-gray-900 mb-8">{t.faq.title}</h2>
          <div className="divide-y divide-gray-100 rounded-2xl border border-gray-100">
            {t.faq.items.map((item, i) => (
              <details key={item.q} className="group" open={i === 0}>
                <summary className="flex min-h-[56px] cursor-pointer list-none items-center justify-between gap-4 px-5 py-3 font-semibold text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500 [&::-webkit-details-marker]:hidden">
                  {item.q}
                  <ChevronDown className="h-4 w-4 shrink-0 text-gray-400 transition-transform group-open:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
                </summary>
                <p className="px-5 pb-5 text-gray-600 leading-relaxed">{item.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Closing CTA */}
      <section className="py-14 sm:py-20 px-4 sm:px-6 bg-slate-950">
        <div className="max-w-2xl mx-auto text-center">
          <Globe2 className="h-10 w-10 text-indigo-400 mx-auto mb-4" aria-hidden="true" />
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4">{t.cta.title}</h2>
          <p className="text-gray-300 mb-8">{t.cta.body}</p>
          <Link href="/world" className={buttonVariants({ variant: "primary", size: "lg" })}>
            {t.cta.button} <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
      </section>

      <MarketingFooter />
    </div>
  );
}

function FeaturedVideo({
  feature, label, categoryName, locale,
}: {
  feature: WorldFeature; label: string; categoryName: string | null | undefined; locale: string;
}) {
  const title = feature.title || feature.subject_text || "";
  const place = countryName(feature.subject_region, locale);
  const Icon = iconForCategory(feature.subject_category);
  const color = colorForCategory(feature.subject_category);
  return (
    <Link
      href={`/world/feature/${feature.id}`}
      className="group relative mx-auto block w-full max-w-[260px] sm:max-w-[300px] focus-visible:outline-none"
    >
      <div className="absolute -inset-4 bg-gradient-to-r from-indigo-600/25 to-purple-600/25 rounded-3xl blur-xl" aria-hidden="true" />
      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-slate-900 shadow-2xl group-focus-visible:ring-2 group-focus-visible:ring-indigo-400">
        <div className="relative aspect-[9/16]">
          {/* eslint-disable-next-line @next/next/no-img-element -- external storage URL */}
          <img src={feature.thumbnail_url!} alt="" className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.03] motion-reduce:transition-none" />
          <div className="absolute inset-0 bg-gradient-to-t from-slate-950/95 via-slate-950/20 to-transparent" aria-hidden="true" />
          <span className="absolute left-3 top-3 rounded-full bg-white/95 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-900">{label}</span>
          <span className="absolute inset-0 flex items-center justify-center" aria-hidden="true">
            <span className="flex h-14 w-14 items-center justify-center rounded-full bg-black/45 text-white ring-1 ring-white/40 backdrop-blur-sm transition-transform group-hover:scale-110 motion-reduce:transition-none">
              <Play className="h-6 w-6 translate-x-0.5" fill="currentColor" />
            </span>
          </span>
          <div className="absolute inset-x-0 bottom-0 p-4">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {categoryName && (
                <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold text-white" style={{ background: color }}>
                  <Icon className="h-3 w-3" aria-hidden="true" /> {categoryName}
                </span>
              )}
              {place && <span className="text-gray-200"><span aria-hidden="true">{flagEmoji(feature.subject_region)}</span> {place}</span>}
            </div>
            <p className="mt-2 text-base font-bold leading-snug text-white">{title}</p>
          </div>
        </div>
      </div>
    </Link>
  );
}

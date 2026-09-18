import Link from "next/link";
import {
  Zap, ArrowRight, CheckCircle, Film, Clock, Megaphone, Music, Target,
  Lightbulb, ShoppingBag, Drama, Globe2, MapPin, Layers, History, Database,
  ShieldCheck, Radio, Play,
} from "lucide-react";
import { buttonVariants } from "@/components/ui/Button";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";

type SampleIdea = {
  platform: string;
  platformColor: string;
  format: string;
  viral_angle: string;
  viralColor: string;
  hook: string;
  caption: string;
  cta: string;
  posting_time: string;
  hashtags: string[];
  trend_connection: string;
  music_mood: string;
};

// Fallback only — used if the live /public/sample-ideas backend call fails
// or hasn't produced any ideas yet (e.g. a fresh environment with no
// pipeline history). See getSampleIdeas() below for the live path.
const MOCK_IDEAS: SampleIdea[] = [
  {
    platform: "TikTok",
    platformColor: "bg-pink-100 text-pink-700",
    format: "talking head",
    viral_angle: "hot take",
    viralColor: "bg-orange-50 text-orange-600 border-orange-200",
    hook: "Nobody's talking about why quiet luxury is actually dying",
    caption: "The aesthetic economy shifted overnight and most creators missed it. Here's what's actually dominating feeds right now — and how to get ahead of it before everyone else catches on. This is your 30-second cultural brief.",
    cta: "Save this and post by Thursday",
    posting_time: "Thursday 6–8 PM EST",
    hashtags: ["#quietluxury", "#aestheticlife", "#fashiontrends", "#ootd", "#styleinspo"],
    trend_connection: "Viral 'de-influencing' thread on Reddit gained 40k upvotes overnight",
    music_mood: "Dark minimalist piano",
  },
  {
    platform: "Instagram",
    platformColor: "bg-purple-100 text-purple-700",
    format: "carousel",
    viral_angle: "myth-bust",
    viralColor: "bg-yellow-50 text-yellow-700 border-yellow-200",
    hook: "3 posting strategies killing your reach (everyone's doing #2)",
    caption: "The algorithm changed in March and most of the 'expert' advice is now actively hurting your growth. Swipe through to see what's actually working in 2025, backed by real creator data from the past 30 days.",
    cta: "Share with a creator friend",
    posting_time: "Tuesday 12–2 PM EST",
    hashtags: ["#contentcreator", "#instagramgrowth", "#socialmediatips", "#creatoreconomy", "#growthhacks"],
    trend_connection: "Creator economy thread went viral on X — 200k impressions in 6 hours",
    music_mood: "Upbeat lo-fi hip hop",
  },
];

const PLATFORM_COLORS: Record<string, string> = {
  TikTok: "bg-pink-100 text-pink-700",
  YouTube: "bg-red-100 text-red-700",
  Instagram: "bg-purple-100 text-purple-700",
  Xiaohongshu: "bg-rose-100 text-rose-700",
  "X/Twitter": "bg-sky-100 text-sky-700",
  Reddit: "bg-orange-100 text-orange-700",
  Pinterest: "bg-red-50 text-red-600",
};

const VIRAL_COLORS: [string, string][] = [
  ["hot take", "bg-orange-50 text-orange-600 border-orange-200"],
  ["myth", "bg-yellow-50 text-yellow-700 border-yellow-200"],
  ["pov", "bg-indigo-50 text-indigo-600 border-indigo-200"],
  ["transformation", "bg-emerald-50 text-emerald-600 border-emerald-200"],
  ["duet", "bg-pink-50 text-pink-600 border-pink-200"],
  ["challenge", "bg-blue-50 text-blue-600 border-blue-200"],
  ["reaction", "bg-purple-50 text-purple-600 border-purple-200"],
  ["tutorial", "bg-teal-50 text-teal-600 border-teal-200"],
];

function viralAngleClass(angle: string): string {
  const lower = angle.toLowerCase();
  const match = VIRAL_COLORS.find(([key]) => lower.includes(key));
  return match ? match[1] : "bg-gray-50 text-gray-600 border-gray-200";
}

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

type RawSampleIdea = {
  hook?: string;
  caption?: string;
  cta?: string;
  music_mood?: string;
  platform?: string;
  trend_connection?: string;
  format?: string;
  viral_angle?: string;
  posting_time?: string;
  hashtag_strategy?: string;
};

// Fetches yesterday's real content ideas from the trend engine so the
// creator section's "sample brief" shows genuine output, not frozen mock
// copy. Revalidates hourly (new ideas land once/day); falls back to
// MOCK_IDEAS on any failure, timeout, or empty result so the page never
// breaks on a backend hiccup.
async function getSampleIdeas(): Promise<{ ideas: SampleIdea[]; trendDate: string | null; live: boolean }> {
  try {
    const res = await fetch(`${RAILWAY}/public/sample-ideas?limit=2`, {
      next: { revalidate: 3600 },
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) throw new Error(`sample-ideas ${res.status}`);
    const data = await res.json();
    const raw: RawSampleIdea[] = Array.isArray(data?.ideas) ? data.ideas : [];
    const ideas: SampleIdea[] = raw
      .filter((idea) => idea.hook && idea.caption)
      .map((idea) => ({
        platform: idea.platform ?? "TikTok",
        platformColor: PLATFORM_COLORS[idea.platform ?? ""] ?? "bg-gray-100 text-gray-700",
        format: idea.format ?? "video",
        viral_angle: idea.viral_angle ?? "hot take",
        viralColor: viralAngleClass(idea.viral_angle ?? ""),
        hook: idea.hook!,
        caption: idea.caption!,
        cta: idea.cta ?? "",
        posting_time: idea.posting_time ?? "",
        hashtags: (idea.hashtag_strategy ?? "").split(/\s+/).filter((h) => h.startsWith("#")),
        trend_connection: idea.trend_connection ?? "",
        music_mood: idea.music_mood ?? "",
      }));

    if (ideas.length === 0) throw new Error("no live ideas yet");
    return { ideas, trendDate: data?.trend_date ?? null, live: true };
  } catch {
    return { ideas: MOCK_IDEAS, trendDate: null, live: false };
  }
}

type WorldStats = { countries: number; videos: number; deepCountries: number };

// A region only counts as "tracked" with a meaningful volume of real rows: the
// endpoint also lists a long tail of regions with 1-3 stray rows, which would
// inflate the headline number. "Deep" = two or more months of daily history.
const MIN_TRACKED_ROWS = 20;
const DEEP_HISTORY_DAYS = 50;

// Real numbers from the same endpoint the map uses. Any failure returns null
// and the stat bar falls back to figures that don't depend on live data — the
// page never shows a made-up count.
async function getWorldStats(): Promise<WorldStats | null> {
  try {
    const res = await fetch(`${RAILWAY}/world/regions`, {
      next: { revalidate: 3600 },
      signal: AbortSignal.timeout(6000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const regions: { trend_count?: number; feature_count?: number; trend_days?: number }[] = Array.isArray(data?.regions) ? data.regions : [];
    if (regions.length === 0) return null;
    return {
      countries: regions.filter((r) => (r.trend_count ?? 0) >= MIN_TRACKED_ROWS).length,
      videos: regions.reduce((sum, r) => sum + (r.feature_count ?? 0), 0),
      deepCountries: regions.filter((r) => (r.trend_days ?? 0) >= DEEP_HISTORY_DAYS).length,
    };
  } catch {
    return null;
  }
}

const SOURCES = ["Wikipedia", "UNESCO World Heritage", "TikTok", "YouTube", "Google Trends", "Reddit", "X / Twitter"];

const HOW_IT_WORKS = [
  {
    icon: Database,
    title: "We start from something real",
    desc: "Every subject comes from a real source: a Wikipedia article, a UNESCO World Heritage site, or what people in that country are actually watching and searching right now. Nothing is dreamed up from thin air.",
    accent: "text-indigo-500",
    bg: "bg-indigo-50",
  },
  {
    icon: ShieldCheck,
    title: "AI writes it, then checks itself",
    desc: "The script is written only from the source text. A second AI pass then flags any claim the source doesn't back up, and it gets rewritten. A person chooses every subject before anything is made.",
    accent: "text-emerald-500",
    bg: "bg-emerald-50",
  },
  {
    icon: Play,
    title: "You explore it in seconds",
    desc: "The result is a short narrated video pinned to a place on the map, with a link back to its source. Watch one, then follow your curiosity to the next country, theme, or century.",
    accent: "text-purple-500",
    bg: "bg-purple-50",
  },
];

const WAYS_IN = [
  {
    icon: MapPin,
    title: "By place",
    desc: "Click any country to see its videos and what is trending there today.",
  },
  {
    icon: Layers,
    title: "By theme",
    desc: "Places, phenomena, species, technology, Gen-Z culture. Filter the whole map to what you care about.",
  },
  {
    icon: History,
    title: "Through time",
    desc: "Slide back through recent trend history, or jump to a historical era. Click France, drag to the French Revolution.",
  },
];

const TRUST = [
  "Every video links to its source",
  "Scripts are fact-checked against that source",
  "A person picks each subject",
  "Trend data refreshes four times a day",
];

const PRODUCTS = [
  {
    icon: Lightbulb,
    name: "Posting Ideation",
    status: "Live",
    statusColor: "bg-emerald-50 text-emerald-600 border-emerald-200",
    desc: "Trend-driven content ideas, personalized to your brand and delivered to your dashboard every morning.",
    href: "/products/posting-ideation",
    cta: "See how it works",
    accent: "text-indigo-500",
    bg: "bg-indigo-50",
  },
  {
    icon: ShoppingBag,
    name: "Shopify Reel Building",
    status: "Now piloting",
    statusColor: "bg-amber-50 text-amber-600 border-amber-200",
    desc: "Connect your Shopify store and get AI post ideas and short-form reels built from your real product photos.",
    href: "/products/shopify",
    cta: "Explore Shopify Reel Building",
    accent: "text-emerald-500",
    bg: "bg-emerald-50",
  },
  {
    icon: Drama,
    name: "Character-Based Posting",
    status: "Beta",
    statusColor: "bg-purple-50 text-purple-600 border-purple-200",
    desc: "Build original cartoon characters and let AI animate them into short videos that riff on what's trending.",
    href: "/products/culturetoons",
    cta: "Explore Character-Based Posting",
    accent: "text-purple-500",
    bg: "bg-purple-50",
  },
];

const PLANS = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    features: [
      "3 personalized ideas/day",
      "All 7 platforms",
      "Daily digest",
      "Hook + caption + CTA",
      "1 content profile",
    ],
    cta: "Get started free",
    href: "/signup",
    highlighted: false,
  },
  {
    name: "Pro",
    price: "$29",
    period: "/month",
    features: [
      "3 daily ideas + generate ideas for any trend",
      "All 7 platforms",
      "Daily digest by 7 AM",
      "Viral angle + posting time + hashtags",
      "AI voiceover, music & video",
      "Up to 10 content profiles",
      "On-demand refresh",
    ],
    cta: "Start 7-day free trial",
    href: "/signup?plan=pro",
    highlighted: true,
  },
];

function MockCard({ idea }: { idea: SampleIdea }) {
  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-5 flex flex-col gap-3 shadow-sm text-left">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-xs font-bold text-gray-300">#01</span>
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          <span className={`inline-flex items-center gap-1 text-xs font-medium rounded-full border px-2.5 py-1 ${idea.viralColor}`}>
            <Zap className="h-3 w-3" />
            {idea.viral_angle}
          </span>
          <span className="inline-flex items-center gap-1 text-xs font-medium rounded-full bg-gray-100 text-gray-500 px-2.5 py-1">
            <Film className="h-3 w-3" />
            {idea.format}
          </span>
          <span className={`text-xs font-semibold rounded-full px-2.5 py-1 ${idea.platformColor}`}>
            {idea.platform}
          </span>
        </div>
      </div>

      <p className="text-sm font-bold text-gray-900 leading-snug">{idea.hook}</p>
      <p className="text-xs text-gray-500 leading-relaxed line-clamp-3">{idea.caption}</p>

      <div className="flex flex-wrap gap-1">
        {idea.hashtags.map(h => (
          <span key={h} className="text-xs rounded-full bg-indigo-50 text-indigo-600 px-2 py-0.5">{h}</span>
        ))}
      </div>

      <div className="space-y-1.5 border-t border-gray-50 pt-2">
        <div className="flex items-center gap-2">
          <Megaphone className="h-3 w-3 text-blue-400 shrink-0" />
          <p className="text-xs text-gray-500">{idea.cta}</p>
        </div>
        <div className="flex items-center gap-2">
          <Clock className="h-3 w-3 text-amber-400 shrink-0" />
          <p className="text-xs text-gray-500">{idea.posting_time}</p>
        </div>
        <div className="flex items-center gap-2">
          <Music className="h-3 w-3 text-purple-400 shrink-0" />
          <p className="text-xs text-gray-500">{idea.music_mood}</p>
        </div>
        <div className="flex items-center gap-2">
          <Target className="h-3 w-3 text-green-400 shrink-0" />
          <p className="text-xs text-gray-500 line-clamp-1">{idea.trend_connection}</p>
        </div>
      </div>
    </div>
  );
}

// Illustrative card for the hero — labeled "Example" and built only from
// facts verified against the real UNESCO record and Wikipedia article for
// Carcassonne, so it explains the format without inventing a video or a trend.
function WorldExampleCard() {
  return (
    <div className="relative mx-auto w-full max-w-md lg:max-w-none">
      <div className="absolute -inset-4 bg-gradient-to-r from-indigo-600/20 to-purple-600/20 rounded-3xl blur-xl" />
      <div className="relative rounded-2xl border border-white/10 bg-slate-900/80 p-5 sm:p-6 text-left shadow-2xl backdrop-blur">
        <div className="flex items-center justify-between gap-3 mb-4">
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-300">
            <MapPin className="h-3.5 w-3.5" /> France
          </span>
          <span className="text-[11px] font-medium uppercase tracking-wide text-gray-500">Example</span>
        </div>

        <div className="relative aspect-video rounded-xl bg-gradient-to-br from-indigo-900/60 via-slate-800 to-purple-900/50 border border-white/5 flex items-center justify-center mb-4">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/10 border border-white/20">
            <Play className="h-5 w-5 text-white ml-0.5" />
          </span>
          <span className="absolute bottom-2 right-2 rounded bg-black/50 px-1.5 py-0.5 text-[11px] text-gray-300">0:30</span>
        </div>

        <h3 className="text-base sm:text-lg font-bold text-white leading-snug">Historic Fortified City of Carcassonne</h3>
        <p className="mt-1 text-sm text-gray-400 leading-relaxed">
          A fortified settlement since the pre-Roman period, and a landmark of modern conservation.
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 border border-amber-500/20 px-2.5 py-1 text-xs font-medium text-amber-300">
            <History className="h-3 w-3" /> History
          </span>
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 text-xs font-medium text-emerald-300">
            <ShieldCheck className="h-3 w-3" /> Fact-checked
          </span>
          <span className="inline-flex items-center gap-1 rounded-full bg-white/5 border border-white/10 px-2.5 py-1 text-xs font-medium text-gray-300">
            <Database className="h-3 w-3" /> Source: UNESCO
          </span>
        </div>
      </div>
    </div>
  );
}

export default async function LandingPage() {
  const [{ ideas: sampleIdeas, trendDate, live }, world] = await Promise.all([getSampleIdeas(), getWorldStats()]);
  const sampleCaption = live
    ? `Real ideas from Culturix's ${trendDate ?? "latest"} brief, regenerated daily`
    : "Sample ideas generated for a fashion brand targeting Gen Z on TikTok + Instagram";

  const stats: { val: string; label: string }[] = [
    { val: world ? `${world.countries}` : "35", label: "countries tracked" },
    ...(world && world.deepCountries > 0 ? [{ val: `${world.deepCountries}`, label: "countries with 2+ months of history" }] : []),
    { val: "4×", label: "daily data refresh" },
    ...(world && world.videos > 0 ? [{ val: `${world.videos}`, label: "videos on the map" }] : [{ val: "Free", label: "to explore the map" }]),
  ];

  return (
    <div className="min-h-screen bg-white overflow-x-hidden">
      <MarketingHeader transparent />

      {/* Hero */}
      <section className="pt-24 pb-14 sm:pt-32 sm:pb-20 px-4 sm:px-6 bg-slate-950 relative overflow-hidden">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-1/4 left-1/3 w-72 h-72 sm:w-96 sm:h-96 bg-indigo-600/20 rounded-full blur-3xl" />
          <div className="absolute bottom-0 right-1/4 w-64 h-64 sm:w-80 sm:h-80 bg-purple-600/15 rounded-full blur-3xl" />
        </div>

        <div className="max-w-6xl mx-auto relative">
          <div className="grid lg:grid-cols-2 gap-10 lg:gap-12 items-center">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs font-semibold px-3 py-1.5 mb-5 sm:mb-6">
                <Globe2 className="h-3.5 w-3.5" />
                Culturix World · a living atlas of culture
              </div>
              <h1 className="text-3xl min-[400px]:text-4xl sm:text-5xl font-extrabold text-white leading-tight mb-5 sm:mb-6">
                Explore the world&rsquo;s culture,{" "}
                <span className="bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                  one short video at a time
                </span>
              </h1>
              <p className="text-base sm:text-lg text-gray-400 mb-7 sm:mb-8 leading-relaxed">
                Culturix World is an interactive map of history, heritage, technology and humor. Pick a country, slide through time, and watch short videos built from real sources like Wikipedia and UNESCO, and tied to what people there are talking about right now.
              </p>

              <div className="flex flex-col sm:flex-row gap-3">
                <Link href="/world" className={`${buttonVariants({ variant: "primary", size: "lg" })} px-6 sm:px-8`}>
                  Explore the map <ArrowRight className="h-4 w-4" />
                </Link>
                <Link
                  href="#how-it-works"
                  className="inline-flex items-center justify-center gap-2 bg-white/5 border border-white/10 text-gray-300 font-semibold px-6 sm:px-8 py-4 rounded-xl hover:bg-white/10 transition-colors text-base"
                >
                  How it works
                </Link>
              </div>
            </div>

            <WorldExampleCard />
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="py-8 sm:py-10 border-b border-gray-100 bg-white">
        <div className={`max-w-4xl mx-auto px-4 sm:px-6 grid grid-cols-2 gap-x-4 gap-y-6 text-center ${stats.length >= 4 ? "md:grid-cols-4" : "md:grid-cols-3"}`}>
          {stats.map((s) => (
            <div key={s.label}>
              <p className="text-2xl sm:text-3xl font-extrabold text-indigo-600">{s.val}</p>
              <p className="text-xs sm:text-sm text-gray-500 mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-14 sm:py-20 px-4 sm:px-6 scroll-mt-16">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10 sm:mb-14">
            <p className="text-xs font-semibold text-indigo-500 uppercase tracking-wide mb-3">How it works</p>
            <h2 className="text-2xl sm:text-4xl font-bold text-gray-900 mb-4">
              Real sources in, short videos out
            </h2>
            <p className="text-gray-500 max-w-xl mx-auto">
              Most AI video is made up. Ours starts from a real article or a real trend, and shows its work.
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-4 sm:gap-6">
            {HOW_IT_WORKS.map((s, i) => (
              <div key={s.title} className="rounded-2xl border border-gray-100 p-5 sm:p-6">
                <div className="flex items-center gap-3 mb-4">
                  <div className={`h-10 w-10 rounded-xl ${s.bg} flex items-center justify-center`}>
                    <s.icon className={`h-5 w-5 ${s.accent}`} />
                  </div>
                  <span className="text-xs font-bold text-gray-300">0{i + 1}</span>
                </div>
                <h3 className="font-semibold text-gray-900 mb-2">{s.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
              </div>
            ))}
          </div>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
            <span className="text-xs text-gray-400 mr-1">Built from</span>
            {SOURCES.map((name) => (
              <span key={name} className="text-xs font-medium rounded-full bg-gray-50 border border-gray-100 text-gray-600 px-3 py-1.5">{name}</span>
            ))}
          </div>
        </div>
      </section>

      {/* Ways in */}
      <section className="py-14 sm:py-20 px-4 sm:px-6 bg-gray-50">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10 sm:mb-14">
            <h2 className="text-2xl sm:text-4xl font-bold text-gray-900 mb-4">One map, three ways in</h2>
            <p className="text-gray-500 max-w-xl mx-auto">
              Wander, or go looking for something specific. Either way you are one tap from a video.
            </p>
          </div>
          <div className="grid sm:grid-cols-3 gap-4 sm:gap-6">
            {WAYS_IN.map((w) => (
              <div key={w.title} className="rounded-2xl border border-gray-100 bg-white p-5 sm:p-6">
                <div className="h-10 w-10 rounded-xl bg-indigo-50 flex items-center justify-center mb-4">
                  <w.icon className="h-5 w-5 text-indigo-500" />
                </div>
                <h3 className="font-semibold text-gray-900 mb-2">{w.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{w.desc}</p>
              </div>
            ))}
          </div>
          <div className="mt-10 text-center">
            <Link href="/world" className={`${buttonVariants({ variant: "primary", size: "lg" })} w-full sm:w-auto`}>
              Open the map <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* Trust */}
      <section className="py-14 sm:py-20 px-4 sm:px-6 bg-slate-950">
        <div className="max-w-4xl mx-auto grid md:grid-cols-2 gap-8 md:gap-12 items-center">
          <div>
            <div className="inline-flex items-center gap-2 text-emerald-300 text-xs font-semibold uppercase tracking-wide mb-4">
              <Radio className="h-4 w-4" /> Real, not invented
            </div>
            <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4">
              Culture deserves better than AI guesswork
            </h2>
            <p className="text-gray-400 leading-relaxed">
              Short-form video is where people learn about the world now, and too much of it is confidently wrong. Culturix keeps a paper trail for every video so you can check it yourself.
            </p>
          </div>
          <ul className="space-y-3">
            {TRUST.map((t) => (
              <li key={t} className="flex items-start gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3.5 text-sm sm:text-base text-gray-200">
                <CheckCircle className="h-5 w-5 shrink-0 text-emerald-400 mt-0.5" />
                {t}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* For creators */}
      <section id="creators" className="py-14 sm:py-20 px-4 sm:px-6 scroll-mt-16">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10 sm:mb-14">
            <p className="text-xs font-semibold text-indigo-500 uppercase tracking-wide mb-3">For creators &amp; brands</p>
            <h2 className="text-2xl sm:text-4xl font-bold text-gray-900 mb-4">
              The same trend engine, working for your brand
            </h2>
            <p className="text-gray-500 max-w-xl mx-auto">
              The signals behind the map also power a set of tools that turn what is happening online into content you can post.
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-4 sm:gap-6">
            {PRODUCTS.map((p) => (
              <div key={p.name} className="rounded-2xl border border-gray-100 bg-white p-5 sm:p-6 flex flex-col">
                <div className="flex items-center justify-between mb-4">
                  <div className={`h-10 w-10 rounded-xl ${p.bg} flex items-center justify-center`}>
                    <p.icon className={`h-5 w-5 ${p.accent}`} />
                  </div>
                  <span className={`text-xs font-medium rounded-full border px-2.5 py-1 ${p.statusColor}`}>
                    {p.status}
                  </span>
                </div>
                <h3 className="font-semibold text-gray-900 mb-2">{p.name}</h3>
                <p className="text-sm text-gray-500 leading-relaxed mb-5 flex-1">{p.desc}</p>
                <Link
                  href={p.href}
                  className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-indigo-600 hover:text-indigo-700 transition-colors"
                >
                  {p.cta} <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Sample brief */}
      <section id="sample" className="py-14 sm:py-20 px-4 sm:px-6 bg-gray-50 scroll-mt-16">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10">
            <h2 className="text-2xl sm:text-3xl font-bold text-gray-900 mb-4">
              What a daily brief looks like
            </h2>
            <p className="text-gray-500 max-w-xl mx-auto">
              Every idea includes a hook, caption, CTA, viral angle, best posting time, hashtags, music mood, and an AI video brief.
            </p>
          </div>
          <div className="grid md:grid-cols-2 gap-4 sm:gap-5">
            {sampleIdeas.map((idea, i) => (
              <MockCard key={i} idea={idea} />
            ))}
          </div>
          <p className="text-center text-xs text-gray-400 mt-6">
            {sampleCaption}
          </p>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="py-14 sm:py-20 px-4 sm:px-6 scroll-mt-16">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-2xl sm:text-3xl font-bold text-center text-gray-900 mb-4">
            Simple, transparent pricing
          </h2>
          <p className="text-center text-gray-500 mb-10 sm:mb-12">
            The map is free to explore. Creator plans cover the daily brief and AI media tools.
          </p>
          <div className="grid sm:grid-cols-2 gap-4 sm:gap-6">
            {PLANS.map((p) => (
              <div
                key={p.name}
                className={`rounded-2xl p-6 sm:p-8 ${
                  p.highlighted
                    ? "bg-slate-950 text-white shadow-2xl ring-1 ring-indigo-500/30"
                    : "border border-gray-200 bg-white"
                }`}
              >
                <p className={`text-sm font-semibold mb-2 ${p.highlighted ? "text-indigo-400" : "text-gray-500"}`}>
                  {p.name}
                </p>
                <div className="flex items-baseline gap-1 mb-6">
                  <span className="text-4xl font-extrabold">{p.price}</span>
                  <span className="text-sm text-gray-400">{p.period}</span>
                </div>
                <ul className="space-y-3 mb-8">
                  {p.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm">
                      <CheckCircle className={`h-4 w-4 shrink-0 mt-0.5 ${p.highlighted ? "text-indigo-400" : "text-indigo-500"}`} />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href={p.href}
                  className={`flex min-h-12 items-center justify-center text-center font-semibold rounded-xl transition-colors ${
                    p.highlighted
                      ? "bg-indigo-600 text-white hover:bg-indigo-500"
                      : "bg-gray-900 text-white hover:bg-gray-800"
                  }`}
                >
                  {p.cta}
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer CTA */}
      <section className="py-14 sm:py-20 px-4 sm:px-6 bg-slate-950">
        <div className="max-w-2xl mx-auto text-center">
          <Globe2 className="h-10 w-10 text-indigo-400 mx-auto mb-4" />
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4">Start with a country you love</h2>
          <p className="text-gray-400 mb-8">
            Open the map, pick a place, and watch. Want the daily brief for your brand instead? Your first one is free.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Link href="/world" className={buttonVariants({ variant: "primary", size: "lg" })}>
              Explore the map <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href="/signup"
              className="inline-flex items-center justify-center gap-2 bg-white/5 border border-white/10 text-gray-300 font-semibold px-8 py-4 rounded-xl hover:bg-white/10 transition-colors text-base"
            >
              Get the daily brief free
            </Link>
          </div>
        </div>
      </section>

      <MarketingFooter />
    </div>
  );
}

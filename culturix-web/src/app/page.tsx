import Link from "next/link";
import {
  Zap, ArrowRight, CheckCircle, TrendingUp, Sparkles, Video,
  Clock, Target, Megaphone, Music, Film, History, RefreshCw,
} from "lucide-react";

const MOCK_IDEAS = [
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

const PLATFORMS = [
  { name: "TikTok", color: "bg-pink-500" },
  { name: "YouTube", color: "bg-red-500" },
  { name: "Reddit", color: "bg-orange-500" },
  { name: "X / Twitter", color: "bg-sky-500" },
  { name: "Xiaohongshu", color: "bg-rose-500" },
];

const FEATURES = [
  {
    icon: TrendingUp,
    title: "Live signal radar",
    desc: "We collect thousands of posts per day across TikTok, YouTube, Reddit, X, and Xiaohongshu — tracking engagement velocity, not just volume.",
    accent: "text-indigo-500",
    bg: "bg-indigo-50",
  },
  {
    icon: Sparkles,
    title: "Cultural cluster AI",
    desc: "Our AI groups signals into named cultural moments — complete with emotional theme, why it matters, and which audience segments are driving it. Every cluster passes an AI safety and legitimacy check before it ever reaches your brief.",
    accent: "text-purple-500",
    bg: "bg-purple-50",
  },
  {
    icon: History,
    title: "Recurring-trend awareness",
    desc: "Culturix remembers every trend it's ever seen — so it knows whether something is a real weekly pattern, a seasonal moment that comes back every year, or a one-off spike. Your posting timing gets grounded in actual history, not a guess.",
    accent: "text-amber-500",
    bg: "bg-amber-50",
  },
  {
    icon: Target,
    title: "Persona-matched ideas",
    desc: "Each idea is calibrated to your brand: your tone, your audience age range, your platforms. Ten ideas that read like a strategist wrote them for you.",
    accent: "text-pink-500",
    bg: "bg-pink-50",
  },
  {
    icon: RefreshCw,
    title: "Ideas that stay honest",
    desc: "We don't deliver ideas and disappear. Every idea gets a daily freshness audit — see at a glance which are still live, which are aging, and which have gone stale, so you never post something the internet already moved past.",
    accent: "text-sky-500",
    bg: "bg-sky-50",
  },
  {
    icon: Video,
    title: "AI media generation",
    desc: "Pro users can generate a voiceover, background music track, and AI video clip for every single idea — directly from the dashboard.",
    accent: "text-emerald-500",
    bg: "bg-emerald-50",
  },
];

const STEPS = [
  {
    num: "01",
    title: "Set your content profile",
    desc: "Tell us your niche, audience age range, target platforms, tone, and goals. Takes two minutes.",
  },
  {
    num: "02",
    title: "We monitor & cluster",
    desc: "Four times a day our pipeline collects fresh signals and AI-clusters them into named cultural narratives.",
  },
  {
    num: "03",
    title: "Get your daily brief",
    desc: "By 7 AM you have 10 content ideas — each with hook, caption, CTA, viral angle, best posting time, and hashtag strategy.",
  },
];

const PLANS = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    features: [
      "5 content ideas/day",
      "All 5 platforms",
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
      "10 content ideas/day",
      "All 5 platforms",
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

function MockCard({ idea }: { idea: typeof MOCK_IDEAS[0] }) {
  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-5 flex flex-col gap-3 shadow-sm text-left">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-xs font-bold text-gray-300">#01</span>
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          <span className={`inline-flex items-center gap-1 text-xs font-medium rounded-full border px-2.5 py-1 ${idea.viralColor}`}>
            <Zap className="h-3 w-3" />
            {idea.viral_angle}
          </span>
          <span className={`inline-flex items-center gap-1 text-xs font-medium rounded-full bg-gray-100 text-gray-500 px-2.5 py-1`}>
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

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-slate-950/90 backdrop-blur-sm border-b border-white/10">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-indigo-400" />
            <span className="font-bold text-lg tracking-tight text-white">Culturix</span>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/signup" className="text-sm text-gray-400 hover:text-white px-3 py-1.5 transition-colors">
              Sign in
            </Link>
            <Link
              href="/signup"
              className="text-sm bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-500 transition-colors font-medium"
            >
              Get started free
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-32 pb-20 px-4 sm:px-6 bg-slate-950 relative overflow-hidden">
        {/* Background glow */}
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-1/4 left-1/3 w-96 h-96 bg-indigo-600/20 rounded-full blur-3xl" />
          <div className="absolute bottom-0 right-1/4 w-80 h-80 bg-purple-600/15 rounded-full blur-3xl" />
        </div>

        <div className="max-w-6xl mx-auto relative">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            {/* Left copy */}
            <div>
              <div className="inline-flex items-center gap-2 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs font-semibold px-3 py-1.5 mb-6">
                <span className="h-1.5 w-1.5 rounded-full bg-indigo-400 animate-pulse" />
                Monitoring 5 platforms · {new Date().toLocaleDateString("en-US", { weekday: "long" })} brief ready
              </div>
              <h1 className="text-4xl sm:text-5xl font-extrabold text-white leading-tight mb-6">
                Your AI content team{" "}
                <span className="bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                  never sleeps
                </span>
              </h1>
              <p className="text-lg text-gray-400 mb-8 leading-relaxed">
                Culturix monitors thousands of daily signals across TikTok, YouTube, Reddit, X, and Xiaohongshu — clusters emerging cultural moments with AI — and delivers{" "}
                <span className="text-gray-200 font-medium">10 personalized content ideas</span>{" "}
                to your dashboard every morning.
              </p>

              {/* Platform badges */}
              <div className="flex flex-wrap gap-2 mb-8">
                {PLATFORMS.map(p => (
                  <span key={p.name} className="inline-flex items-center gap-1.5 text-xs font-medium rounded-full bg-white/5 border border-white/10 text-gray-300 px-3 py-1.5">
                    <span className={`h-1.5 w-1.5 rounded-full ${p.color}`} />
                    {p.name}
                  </span>
                ))}
              </div>

              <div className="flex flex-col sm:flex-row gap-3">
                <Link
                  href="/signup"
                  className="inline-flex items-center justify-center gap-2 bg-indigo-600 text-white font-semibold px-8 py-4 rounded-xl hover:bg-indigo-500 transition-colors text-base"
                >
                  Start free — no credit card <ArrowRight className="h-4 w-4" />
                </Link>
                <Link
                  href="#sample"
                  className="inline-flex items-center justify-center gap-2 bg-white/5 border border-white/10 text-gray-300 font-semibold px-8 py-4 rounded-xl hover:bg-white/10 transition-colors text-base"
                >
                  See sample brief
                </Link>
              </div>
            </div>

            {/* Right — mock card */}
            <div className="hidden lg:block">
              <div className="relative">
                <div className="absolute -inset-4 bg-gradient-to-r from-indigo-600/20 to-purple-600/20 rounded-3xl blur-xl" />
                <div className="relative">
                  <MockCard idea={MOCK_IDEAS[0]} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Stats bar */}
      <section className="py-10 border-b border-gray-100 bg-white">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 grid grid-cols-2 sm:grid-cols-4 gap-6 text-center">
          {[
            { val: "5",     label: "platforms monitored" },
            { val: "10k+",  label: "signals per day" },
            { val: "10",    label: "ideas per brief" },
            { val: "4×",    label: "daily signal refresh" },
          ].map((s) => (
            <div key={s.label}>
              <p className="text-3xl font-extrabold text-indigo-600">{s.val}</p>
              <p className="text-sm text-gray-500 mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="py-20 px-4 sm:px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl sm:text-4xl font-bold text-gray-900 mb-4">
              Intelligence that works while you sleep
            </h2>
            <p className="text-gray-500 max-w-xl mx-auto">
              Stop scrolling platforms trying to spot trends. Wake up to a briefing that reads like a senior content strategist wrote it for your brand.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 gap-6">
            {FEATURES.map((f) => (
              <div key={f.title} className="rounded-2xl border border-gray-100 p-6 hover:shadow-md transition-shadow">
                <div className={`h-10 w-10 rounded-xl ${f.bg} flex items-center justify-center mb-4`}>
                  <f.icon className={`h-5 w-5 ${f.accent}`} />
                </div>
                <h3 className="font-semibold text-gray-900 mb-2">{f.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Sample brief preview */}
      <section id="sample" className="py-20 px-4 sm:px-6 bg-gray-50">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold text-gray-900 mb-4">
              What your daily brief looks like
            </h2>
            <p className="text-gray-500 max-w-xl mx-auto">
              Every idea includes a hook, caption, CTA, viral angle, optimal posting time, hashtag strategy, music mood, and AI video brief.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 gap-5">
            {MOCK_IDEAS.map((idea, i) => (
              <MockCard key={i} idea={idea} />
            ))}
          </div>
          <p className="text-center text-xs text-gray-400 mt-6">
            Sample ideas generated for a fashion brand targeting Gen Z on TikTok + Instagram
          </p>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-20 px-4 sm:px-6">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-gray-900 mb-14">
            Up and running in 2 minutes
          </h2>
          <div className="grid sm:grid-cols-3 gap-10">
            {STEPS.map((s, i) => (
              <div key={s.num} className="relative text-center">
                {i < STEPS.length - 1 && (
                  <div className="hidden sm:block absolute top-6 left-1/2 w-full h-px bg-gray-100" />
                )}
                <div className="relative inline-flex items-center justify-center h-12 w-12 rounded-full bg-indigo-50 text-indigo-600 font-bold text-sm mb-4 mx-auto">
                  {s.num}
                </div>
                <h3 className="font-semibold text-gray-900 mb-2">{s.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="py-20 px-4 sm:px-6 bg-gray-50">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-gray-900 mb-4">
            Simple, transparent pricing
          </h2>
          <p className="text-center text-gray-500 mb-12">Start free. Upgrade when you need the full brief.</p>
          <div className="grid sm:grid-cols-2 gap-6">
            {PLANS.map((p) => (
              <div
                key={p.name}
                className={`rounded-2xl p-8 ${
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
                  <span className={`text-sm ${p.highlighted ? "text-gray-400" : "text-gray-400"}`}>
                    {p.period}
                  </span>
                </div>
                <ul className="space-y-3 mb-8">
                  {p.features.map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm">
                      <CheckCircle className={`h-4 w-4 shrink-0 ${p.highlighted ? "text-indigo-400" : "text-indigo-500"}`} />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href={p.href}
                  className={`block text-center font-semibold py-3 rounded-xl transition-colors ${
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
      <section className="py-20 px-4 sm:px-6 bg-slate-950">
        <div className="max-w-2xl mx-auto text-center">
          <Zap className="h-10 w-10 text-indigo-400 mx-auto mb-4" />
          <h2 className="text-3xl font-bold text-white mb-4">Stop guessing what to post</h2>
          <p className="text-gray-400 mb-8">
            Start with signals. Your first brief is free — no credit card required.
          </p>
          <Link
            href="/signup"
            className="inline-flex items-center gap-2 bg-indigo-600 text-white font-semibold px-8 py-4 rounded-xl hover:bg-indigo-500 transition-colors"
          >
            Get started free <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-8 px-4 sm:px-6 border-t border-white/5 bg-slate-950">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-sm">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-indigo-400" />
            <span className="font-semibold text-gray-300">Culturix</span>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/privacy" className="text-gray-500 hover:text-gray-300 transition-colors">Privacy Policy</Link>
            <Link href="/terms" className="text-gray-500 hover:text-gray-300 transition-colors">Terms of Service</Link>
          </div>
          <p className="text-gray-600">© 2026 Culturix. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}

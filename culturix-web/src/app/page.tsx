import Link from "next/link";
import { TrendingUp, Zap, Users, Mail, ArrowRight, CheckCircle } from "lucide-react";

const features = [
  {
    icon: TrendingUp,
    title: "5-Platform Signal Capture",
    description:
      "We monitor TikTok, YouTube Shorts, X/Twitter, Xiaohongshu, and Reddit simultaneously — so you never miss an emerging cultural moment.",
  },
  {
    icon: Zap,
    title: "AI Trend Clustering",
    description:
      "DeepSeek groups thousands of daily signals into coherent cultural narratives with emotional themes, viral signals, and why-it-matters context.",
  },
  {
    icon: Users,
    title: "Persona-Matched Ideas",
    description:
      "Tell us your audience, niche, and tone. Our AI strategist generates 10 content ideas calibrated exactly to your brand — with hooks, captions, CTAs, and music moods.",
  },
  {
    icon: Mail,
    title: "Inbox by 7 AM",
    description:
      "No dashboards to check. Your personalized digest lands in your inbox before the workday starts, ready to brief your team or post directly.",
  },
];

const steps = [
  {
    num: "01",
    title: "Set your profile",
    desc: "Tell us your audience, platforms, goals, and content tone in a 2-minute onboarding.",
  },
  {
    num: "02",
    title: "We monitor & cluster",
    desc: "Every 2 hours we collect thousands of signals and AI-cluster them into cultural trends.",
  },
  {
    num: "03",
    title: "Get your digest",
    desc: "Every morning at 7 AM, 10 personalized content ideas mapped to today's trends land in your inbox.",
  },
];

const plans = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    features: ["5 content ideas/day", "2 platforms monitored", "Weekly digest", "Email delivery"],
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
      "Daily digest at 7 AM",
      "Persona matching",
      "On-demand refresh",
      "Priority support",
    ],
    cta: "Start 7-day trial",
    href: "/signup?plan=pro",
    highlighted: true,
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-white/80 backdrop-blur-sm border-b border-gray-100">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-blue-600" />
            <span className="font-bold text-lg tracking-tight">Culturix</span>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/signup" className="text-sm text-gray-600 hover:text-gray-900 px-3 py-1.5">
              Sign in
            </Link>
            <Link
              href="/signup"
              className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
            >
              Get started free
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-32 pb-20 px-4 sm:px-6 bg-gradient-to-b from-blue-50 to-white">
        <div className="max-w-4xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 rounded-full bg-blue-100 text-blue-700 text-xs font-semibold px-3 py-1.5 mb-6">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
            Live trend monitoring across 5 platforms
          </div>
          <h1 className="text-4xl sm:text-6xl font-extrabold text-gray-900 leading-tight mb-6">
            Turn today&apos;s trends into{" "}
            <span className="text-blue-600">tomorrow&apos;s content</span>
          </h1>
          <p className="text-lg sm:text-xl text-gray-600 max-w-2xl mx-auto mb-10">
            Culturix monitors thousands of cultural signals daily, clusters emerging trends with AI,
            and delivers 10 personalized content ideas to your inbox every morning — mapped to your
            audience, niche, and tone.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Link
              href="/signup"
              className="inline-flex items-center justify-center gap-2 bg-blue-600 text-white font-semibold px-8 py-4 rounded-xl hover:bg-blue-700 transition-colors text-base"
            >
              Start free — no credit card <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href="#how-it-works"
              className="inline-flex items-center justify-center gap-2 bg-white text-gray-700 font-semibold px-8 py-4 rounded-xl border border-gray-200 hover:bg-gray-50 transition-colors text-base"
            >
              See how it works
            </Link>
          </div>
          <p className="mt-4 text-sm text-gray-500">
            Join 200+ content creators and brand teams already using Culturix
          </p>
        </div>
      </section>

      {/* Stats bar */}
      <section className="py-8 border-y border-gray-100 bg-white">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 grid grid-cols-3 gap-8 text-center">
          {[
            { val: "5", label: "platforms monitored" },
            { val: "10k+", label: "signals captured daily" },
            { val: "10", label: "personalized ideas per morning" },
          ].map((s) => (
            <div key={s.label}>
              <p className="text-3xl font-extrabold text-blue-600">{s.val}</p>
              <p className="text-sm text-gray-500 mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="py-20 px-4 sm:px-6">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-gray-900 mb-4">
            Intelligence that acts like a full-time trend analyst
          </h2>
          <p className="text-center text-gray-500 mb-12 max-w-xl mx-auto">
            Without Culturix, you spend hours scrolling platforms trying to spot trends. With
            Culturix, you wake up to a briefing.
          </p>
          <div className="grid sm:grid-cols-2 gap-6">
            {features.map((f) => (
              <div key={f.title} className="rounded-2xl border border-gray-100 p-6 hover:shadow-md transition-shadow">
                <div className="h-10 w-10 rounded-xl bg-blue-50 flex items-center justify-center mb-4">
                  <f.icon className="h-5 w-5 text-blue-600" />
                </div>
                <h3 className="font-semibold text-gray-900 mb-2">{f.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{f.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-20 px-4 sm:px-6 bg-gray-50">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-gray-900 mb-12">
            Up and running in 2 minutes
          </h2>
          <div className="grid sm:grid-cols-3 gap-8">
            {steps.map((s) => (
              <div key={s.num} className="text-center">
                <div className="text-5xl font-extrabold text-blue-100 mb-3">{s.num}</div>
                <h3 className="font-semibold text-gray-900 mb-2">{s.title}</h3>
                <p className="text-sm text-gray-500">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="py-20 px-4 sm:px-6">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-gray-900 mb-4">
            Simple, transparent pricing
          </h2>
          <p className="text-center text-gray-500 mb-12">Start free. Upgrade when you need more.</p>
          <div className="grid sm:grid-cols-2 gap-6">
            {plans.map((p) => (
              <div
                key={p.name}
                className={`rounded-2xl p-8 ${
                  p.highlighted
                    ? "bg-blue-600 text-white shadow-xl shadow-blue-200"
                    : "border border-gray-200 bg-white"
                }`}
              >
                <p className={`text-sm font-semibold mb-2 ${p.highlighted ? "text-blue-200" : "text-gray-500"}`}>
                  {p.name}
                </p>
                <div className="flex items-baseline gap-1 mb-6">
                  <span className="text-4xl font-extrabold">{p.price}</span>
                  <span className={`text-sm ${p.highlighted ? "text-blue-200" : "text-gray-400"}`}>
                    {p.period}
                  </span>
                </div>
                <ul className="space-y-3 mb-8">
                  {p.features.map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm">
                      <CheckCircle className={`h-4 w-4 shrink-0 ${p.highlighted ? "text-blue-200" : "text-blue-500"}`} />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href={p.href}
                  className={`block text-center font-semibold py-3 rounded-xl transition-colors ${
                    p.highlighted
                      ? "bg-white text-blue-600 hover:bg-blue-50"
                      : "bg-blue-600 text-white hover:bg-blue-700"
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
      <section className="py-20 px-4 sm:px-6 bg-blue-600">
        <div className="max-w-2xl mx-auto text-center text-white">
          <h2 className="text-3xl font-bold mb-4">Stop guessing what to post</h2>
          <p className="text-blue-200 mb-8">
            Start with signals. Get your first digest free — no credit card required.
          </p>
          <Link
            href="/signup"
            className="inline-flex items-center gap-2 bg-white text-blue-600 font-semibold px-8 py-4 rounded-xl hover:bg-blue-50 transition-colors"
          >
            Get started free <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-8 px-4 sm:px-6 border-t border-gray-100">
        <div className="max-w-6xl mx-auto flex items-center justify-between text-sm text-gray-400">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-blue-600" />
            <span className="font-semibold text-gray-600">Culturix</span>
          </div>
          <p>© 2026 Culturix. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}

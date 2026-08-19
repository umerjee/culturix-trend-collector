import Link from "next/link";
import {
  ArrowRight, Lightbulb, TrendingUp, Sparkles, History, Target, RefreshCw,
} from "lucide-react";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";
import Badge from "@/components/ui/Badge";
import { buttonVariants } from "@/components/ui/Button";

export const metadata = {
  title: "Posting Ideation — Culturix",
  description:
    "Culturix monitors thousands of daily signals across TikTok, YouTube, Instagram, Reddit, X, Xiaohongshu, and Pinterest, clusters emerging cultural moments with AI, and delivers 3 personalized content ideas to your dashboard every morning — generate more for any trend on Pro.",
};

const FEATURES = [
  {
    icon: TrendingUp,
    title: "Live signal radar",
    desc: "We collect thousands of posts per day across TikTok, YouTube, Instagram, Reddit, X, Xiaohongshu, and Pinterest — tracking engagement velocity, not just volume.",
  },
  {
    icon: Sparkles,
    title: "Cultural cluster AI",
    desc: "Our AI groups signals into named cultural moments — complete with emotional theme, why it matters, and which audience segments are driving it.",
  },
  {
    icon: History,
    title: "Recurring-trend awareness",
    desc: "Culturix remembers every trend it's ever seen, so it knows whether something is a weekly pattern, a seasonal moment, or a one-off spike.",
  },
  {
    icon: Target,
    title: "Persona-matched ideas",
    desc: "Each idea is calibrated to your brand: your tone, your audience age range, your platforms — like a strategist wrote it for you.",
  },
];

const STEPS = [
  { num: "01", title: "Set your content profile", desc: "Tell us your niche, audience age range, target platforms, tone, and goals. Takes two minutes." },
  { num: "02", title: "We monitor & cluster", desc: "Four times a day our pipeline collects fresh signals and AI-clusters them into named cultural narratives." },
  { num: "03", title: "Get your daily brief", desc: "By 7 AM you have 3 ready-made content ideas for your top trends — each with hook, caption, CTA, viral angle, posting time, and hashtag strategy." },
];

export default function PostingIdeationProductPage() {
  return (
    <div className="min-h-screen bg-white">
      <MarketingHeader />

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-14">
        <div className="text-center mb-14">
          <Badge variant="success" className="mb-6">
            <Lightbulb className="h-3.5 w-3.5" />
            Live
          </Badge>
          <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 mb-4">
            Posting Ideation
          </h1>
          <p className="text-gray-500 max-w-xl mx-auto leading-relaxed">
            Stop scrolling platforms trying to spot trends. Culturix monitors culture for you and
            delivers a daily brief that reads like a senior content strategist wrote it for your brand.
          </p>
        </div>

        {/* Features */}
        <section className="mb-16 grid sm:grid-cols-2 gap-6">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-2xl border border-gray-100 p-6">
              <div className="h-10 w-10 rounded-xl bg-primary-50 flex items-center justify-center mb-4">
                <f.icon className="h-5 w-5 text-primary-500" />
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">{f.title}</h3>
              <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </section>

        {/* How it works */}
        <section className="mb-16">
          <h2 className="text-lg font-semibold text-gray-900 mb-8 text-center">How it works</h2>
          <div className="grid sm:grid-cols-3 gap-8">
            {STEPS.map((s) => (
              <div key={s.num} className="text-center">
                <div className="inline-flex items-center justify-center h-10 w-10 rounded-full bg-primary-50 text-primary-600 font-bold text-sm mb-3 mx-auto">
                  {s.num}
                </div>
                <h3 className="font-semibold text-gray-900 mb-1">{s.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Why this exists */}
        <section className="mb-16 rounded-2xl bg-gray-50 border border-gray-100 p-6 sm:p-8 flex items-start gap-4">
          <RefreshCw className="h-5 w-5 text-primary-500 mt-0.5 shrink-0" />
          <p className="text-sm text-gray-600 leading-relaxed">
            We don&apos;t deliver ideas and disappear. Every idea gets a daily freshness audit — see at
            a glance which are still live, which are aging, and which have gone stale, so you never
            post something the internet already moved past.
          </p>
        </section>

        {/* CTA */}
        <section className="text-center">
          <Link href="/signup" className={buttonVariants({ variant: "primary", size: "lg" })}>
            Get started free <ArrowRight className="h-4 w-4" />
          </Link>
          <p className="text-xs text-gray-400 mt-4">
            Also want Shopify product reels or AI cartoon characters?{" "}
            <Link href="/#products" className="text-primary-600 hover:underline">See all Culturix products</Link>
          </p>
        </section>
      </main>

      <MarketingFooter />
    </div>
  );
}

import Link from "next/link";
import {
  Zap, ArrowRight, Drama, Wand2, Users, Mic2, Clapperboard, Layers,
} from "lucide-react";

export const metadata = {
  title: "Character-Based Posting — Culturix",
  description:
    "Build original cartoon characters — from a description, a photo, or both — and let AI animate them into short videos that riff on what's trending, in your audience's own culture.",
};

const FEATURES = [
  {
    icon: Wand2,
    title: "Build a character your way",
    desc: "Describe it, upload a reference photo, or both — generate the portrait with AI and regenerate as many times as it takes to get it right.",
  },
  {
    icon: Layers,
    title: "Cultural variants of one character",
    desc: "One base rig, many localized takes — e.g. an “Indian Mom” and a “Nigerian Uncle” variant of the same character, each speaking to a different audience.",
  },
  {
    icon: Users,
    title: "Multiple independent toon accounts",
    desc: "Run several character rosters side by side — a comedy account, a baby-content account, a tech-news account — each with its own characters and connected socials.",
  },
  {
    icon: Mic2,
    title: "Built-in voice, or bring your own",
    desc: "Videos come with character-bound voice and lip sync out of the box. Prefer more control? Connect your own ElevenLabs voice instead.",
  },
];

const STEPS = [
  { num: "01", title: "Create a base character", desc: "Describe it, upload a photo, or both, then generate the portrait — iterate until it looks right." },
  { num: "02", title: "Add cultural variants", desc: "Give the character a variant for each audience you want to reach." },
  { num: "03", title: "Register the character", desc: "One step locks in a consistent look and voice for every future video it appears in." },
  { num: "04", title: "Generate a script", desc: "Pick a live trend and a tone — funny, deadpan, wholesome, chaotic, and more — and get an AI-written skit." },
  { num: "05", title: "Generate the video", desc: "AI animates a multi-shot short video from the script, then post it to your own account." },
];

export default function CultureToonsProductPage() {
  return (
    <div className="min-h-screen bg-white">
      <header className="bg-white border-b border-gray-100 sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-blue-600" />
            <span className="font-bold text-lg tracking-tight">Culturix</span>
          </Link>
          <Link href="/signup" className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors font-medium">
            Get started free
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-14">
        <div className="text-center mb-14">
          <div className="inline-flex items-center gap-2 rounded-full bg-purple-50 border border-purple-200 text-purple-600 text-xs font-semibold px-3 py-1.5 mb-6">
            <Drama className="h-3.5 w-3.5" />
            Beta
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 mb-4">
            Character-Based Posting
          </h1>
          <p className="text-gray-500 max-w-xl mx-auto leading-relaxed">
            Original cartoon characters that riff on culture — built from your own description or photo,
            animated by AI, and grounded in whatever's actually trending today.
          </p>
        </div>

        {/* Features */}
        <section className="mb-16 grid sm:grid-cols-2 gap-6">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-2xl border border-gray-100 p-6">
              <div className="h-10 w-10 rounded-xl bg-purple-50 flex items-center justify-center mb-4">
                <f.icon className="h-5 w-5 text-purple-500" />
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">{f.title}</h3>
              <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </section>

        {/* How it works */}
        <section className="mb-16">
          <h2 className="text-lg font-semibold text-gray-900 mb-8 text-center">How it works</h2>
          <div className="space-y-6">
            {STEPS.map((s) => (
              <div key={s.num} className="flex gap-4 items-start">
                <div className="shrink-0 inline-flex items-center justify-center h-10 w-10 rounded-full bg-purple-50 text-purple-600 font-bold text-sm">
                  {s.num}
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900 mb-1">{s.title}</h3>
                  <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Why this exists */}
        <section className="mb-16 rounded-2xl bg-gray-50 border border-gray-100 p-6 sm:p-8 flex items-start gap-4">
          <Clapperboard className="h-5 w-5 text-purple-500 mt-0.5 shrink-0" />
          <p className="text-sm text-gray-600 leading-relaxed">
            Trends move fast, and not every brand wants to be the one on camera. Character-Based
            Posting gives you a recurring cast that can react to whatever's culturally relevant today,
            without needing a new shoot every time.
          </p>
        </section>

        {/* CTA */}
        <section className="text-center">
          <Link
            href="/signup"
            className="inline-flex items-center gap-2 bg-blue-600 text-white font-semibold px-8 py-4 rounded-xl hover:bg-blue-700 transition-colors"
          >
            Get started free <ArrowRight className="h-4 w-4" />
          </Link>
          <p className="text-xs text-gray-400 mt-4">
            Also want trend-driven content ideas or Shopify product reels?{" "}
            <Link href="/#products" className="text-blue-600 hover:underline">See all Culturix products</Link>
          </p>
        </section>
      </main>
    </div>
  );
}

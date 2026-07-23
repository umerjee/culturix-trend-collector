import Link from "next/link";
import { Zap, ArrowRight, Sparkles, Bell, Send, ShieldCheck } from "lucide-react";
import {
  WHY_NOT_DIRECT_PUBLISH, HOW_IT_WORKS_STEPS, IOS_PUSH_NOTE, LAUNCH_DISCLAIMER,
  PUBLISH_MODE_DESCRIPTIONS, PUBLISH_MODE_LABELS,
} from "@/content/publishingCopy";

export const metadata = {
  title: "How Publishing Works — Culturix",
  description: "Culturix preps your content and notifies you at the right moment — you publish it yourself, from your own account, so nothing about your reach changes.",
};

const STEP_ICONS = [Sparkles, Bell, Send];

export default function HowItWorksPage() {
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
        <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 mb-4 text-center">
          How publishing works
        </h1>
        <p className="text-gray-500 text-center max-w-xl mx-auto mb-14">
          We don&apos;t post on your behalf. We do everything up to the last tap — you keep full control
          of your account, and full access to whatever&apos;s trending.
        </p>

        {/* Why */}
        <section className="mb-16 rounded-2xl bg-gray-50 border border-gray-100 p-6 sm:p-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Why we do it this way</h2>
          <p className="text-sm text-gray-600 leading-relaxed">{WHY_NOT_DIRECT_PUBLISH}</p>
          <p className="text-sm text-gray-600 leading-relaxed mt-3">
            So instead of posting for you, we get everything ready and hand it to you at exactly the
            right moment — one tap from your phone to live.
          </p>
        </section>

        {/* 3 steps */}
        <section className="mb-16">
          <h2 className="text-lg font-semibold text-gray-900 mb-8 text-center">The 3-step process</h2>
          <div className="grid sm:grid-cols-3 gap-8">
            {HOW_IT_WORKS_STEPS.map((step, i) => {
              const Icon = STEP_ICONS[i];
              return (
                <div key={step.title} className="text-center">
                  <div className="inline-flex items-center justify-center h-12 w-12 rounded-full bg-blue-50 text-blue-600 mb-4 mx-auto">
                    <Icon className="h-5 w-5" />
                  </div>
                  <p className="text-xs font-semibold text-gray-400 mb-1">Step {i + 1}</p>
                  <h3 className="font-semibold text-gray-900 mb-2">{step.title}</h3>
                  <p className="text-sm text-gray-500 leading-relaxed">{step.desc}</p>
                </div>
              );
            })}
          </div>
          <p className="text-xs text-gray-400 text-center mt-8 max-w-md mx-auto">{LAUNCH_DISCLAIMER}</p>
        </section>

        {/* Publish modes */}
        <section className="mb-16">
          <h2 className="text-lg font-semibold text-gray-900 mb-6 text-center">Choose how hands-on you want to be</h2>
          <div className="grid sm:grid-cols-3 gap-4">
            {(["manual", "review", "auto"] as const).map((key) => (
              <div key={key} className="rounded-xl border border-gray-200 p-5">
                <p className="text-sm font-semibold text-gray-900 mb-1.5">{PUBLISH_MODE_LABELS[key]}</p>
                <p className="text-xs text-gray-500 leading-relaxed">{PUBLISH_MODE_DESCRIPTIONS[key]}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Notifications note */}
        <section className="mb-16 flex items-start gap-3 rounded-xl bg-amber-50 border border-amber-100 px-5 py-4">
          <ShieldCheck className="h-4 w-4 text-amber-600 mt-0.5 shrink-0" />
          <p className="text-xs text-amber-700 leading-relaxed">{IOS_PUSH_NOTE}</p>
        </section>

        {/* CTA */}
        <section className="text-center">
          <Link
            href="/signup"
            className="inline-flex items-center gap-2 bg-blue-600 text-white font-semibold px-8 py-4 rounded-xl hover:bg-blue-700 transition-colors"
          >
            Get started free <ArrowRight className="h-4 w-4" />
          </Link>
        </section>
      </main>
    </div>
  );
}

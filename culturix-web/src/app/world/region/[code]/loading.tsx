import { ArrowLeft } from "lucide-react";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";

// This page's data comes from five parallel, uncached (`cache: "no-store"`) calls to the
// Railway backend — real network latency the browser has no way to hide on its own. Without this
// file, Next.js shows nothing at all between the click and the slowest of those five resolving,
// which read as a stuck/broken navigation rather than a page that's loading. This skeleton is
// shown automatically the instant the route changes, so the click always has immediate feedback.
export default function WorldRegionLoading() {
  return (
    <div className="min-h-screen bg-white">
      <MarketingHeader />

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-14 animate-pulse">
        <span className="inline-flex items-center gap-1.5 text-sm text-gray-300 mb-8">
          <ArrowLeft className="h-3.5 w-3.5" /> All regions
        </span>

        <div className="h-8 w-56 rounded-lg bg-gray-100 mb-3" />
        <div className="h-4 w-40 rounded bg-gray-100 mb-10" />

        <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5 mb-14">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="rounded-2xl border border-gray-100 overflow-hidden">
              <div className="aspect-[9/16] bg-gray-100" />
              <div className="p-4 space-y-2">
                <div className="h-4 w-16 rounded-full bg-gray-100" />
                <div className="h-4 w-full rounded bg-gray-100" />
                <div className="h-3 w-20 rounded bg-gray-100" />
              </div>
            </div>
          ))}
        </section>

        <div className="h-40 rounded-2xl bg-gray-100" />
      </main>

      <MarketingFooter />
    </div>
  );
}

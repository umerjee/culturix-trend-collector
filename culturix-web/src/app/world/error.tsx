"use client";

import { useEffect } from "react";
import { RefreshCw, Globe2 } from "lucide-react";
import Link from "next/link";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";

// No error.tsx existed anywhere in this app before (not for /world, not even at the root) --
// confirmed live 2026-10-02: a user hitting a server-side exception on /world (most likely
// Vercel's edge-to-Railway latency from their specific region occasionally exceeding the fetch
// timeout, given it reproduced consistently for them but never once for direct testing from
// here) saw Next.js's raw, unstyled default crash page ("Application error... Digest: ...") with
// no way to recover except manually retyping the URL. This doesn't fix whatever is intermittently
// slow -- it fixes the dead end: `reset()` is Next.js's own built-in retry (re-renders the
// segment without a full page reload), given a real button instead of nothing.
export default function WorldError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error("World page error:", error);
  }, [error]);

  return (
    <div className="min-h-screen bg-white">
      <MarketingHeader />
      <main className="max-w-xl mx-auto px-4 sm:px-6 py-24 text-center">
        <div className="inline-flex items-center gap-2 rounded-full bg-purple-50 border border-purple-200 text-purple-600 text-xs font-semibold px-3 py-1.5 mb-6">
          <Globe2 className="h-3.5 w-3.5" />
          Culturix World
        </div>
        <h1 className="text-2xl font-bold text-gray-900 mb-3">
          The map didn&apos;t load this time
        </h1>
        <p className="text-gray-500 leading-relaxed mb-8">
          This is usually a brief hiccup reaching our server, not something wrong with your
          connection. Trying again almost always works.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <button
            onClick={() => reset()}
            className="inline-flex items-center gap-2 rounded-xl bg-purple-600 text-white text-sm font-semibold px-5 py-2.5 hover:bg-purple-700 transition-colors"
          >
            <RefreshCw className="h-4 w-4" /> Try again
          </button>
          <Link
            href="/world"
            className="inline-flex items-center gap-2 rounded-xl border border-gray-200 text-gray-600 text-sm font-semibold px-5 py-2.5 hover:bg-gray-50 transition-colors"
          >
            Start over
          </Link>
        </div>
        {error.digest && (
          <p className="mt-10 text-xs text-gray-300">Reference: {error.digest}</p>
        )}
      </main>
      <MarketingFooter />
    </div>
  );
}

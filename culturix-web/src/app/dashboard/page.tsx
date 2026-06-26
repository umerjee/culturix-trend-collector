import { redirect } from "next/navigation";
import Link from "next/link";
import { RefreshCw, Settings, Zap, TrendingUp, Inbox, ShieldCheck, LayoutList } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import DigestCard from "@/components/DigestCard";
import type { Digest, ContentProfile } from "@/lib/types";

const RAILWAY = "https://culturix-trend-collector-production.up.railway.app";

async function fetchDigest(userId: string, profileId?: string): Promise<Digest | null> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || RAILWAY;
  try {
    const url = profileId
      ? `${apiUrl}/api/digest/${userId}?profile_id=${profileId}`
      : `${apiUrl}/api/digest/${userId}`;
    const res = await fetch(url, {
      cache: "no-store",
      headers: { "x-internal-token": process.env.INTERNAL_API_TOKEN ?? "" },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

async function fetchProfiles(userId: string): Promise<ContentProfile[]> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || RAILWAY;
  try {
    const res = await fetch(`${apiUrl}/users/${userId}/content-profiles`, { cache: "no-store" });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: { profile?: string };
}) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || RAILWAY;

  const isSuperAdmin = user.email === "umer.ali79@gmail.com";
  let plan: "free" | "pro" = isSuperAdmin ? "pro" : "free";
  if (!isSuperAdmin) {
    try {
      const approvalRes = await fetch(`${apiUrl}/api/users/${user.id}/approved`, { cache: "no-store" });
      if (approvalRes.ok) {
        const info = await approvalRes.json();
        if (!info.approved) redirect("/pending");
        if (info.plan === "pro") plan = "pro";
      }
    } catch {
      // Railway unreachable — let user through rather than hard-blocking
    }
  }

  const [profiles, digest] = await Promise.all([
    fetchProfiles(user.id),
    fetchDigest(user.id, searchParams.profile),
  ]);

  const activeProfile = profiles.find((p) => p.id === searchParams.profile) ?? profiles[0] ?? null;
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top nav */}
      <header className="bg-white border-b border-gray-100 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-blue-600" />
            <span className="font-bold text-lg tracking-tight">Culturix</span>
          </div>
          <div className="flex items-center gap-3">
            <form action="/api/generate" method="POST">
              {searchParams.profile && (
                <input type="hidden" name="profile_id" value={searchParams.profile} />
              )}
              <button
                type="submit"
                className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </button>
            </form>
            <Link
              href="/settings"
              className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors"
            >
              <Settings className="h-3.5 w-3.5" /> Settings
            </Link>
            {isSuperAdmin && (
              <Link
                href="/admin"
                className="inline-flex items-center gap-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-lg px-3 py-2 hover:bg-indigo-50 transition-colors"
              >
                <ShieldCheck className="h-3.5 w-3.5" /> Admin
              </Link>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="mb-6">
          <p className="text-sm text-gray-500 mb-1">{today}</p>
          <h1 className="text-2xl font-bold text-gray-900">Your daily content brief</h1>
          {digest?.generated_at && (
            <p className="text-xs text-gray-400 mt-1">
              Generated {new Date(digest.generated_at).toLocaleTimeString()}
            </p>
          )}
        </div>

        {/* Quick stats */}
        {digest && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
            {[
              { val: String(digest.content_ideas?.length ?? 0), label: "ideas ready" },
              { val: String(digest.clusters?.length ?? 0), label: "trend clusters" },
              { val: activeProfile?.target_platforms?.length ? String(activeProfile.target_platforms.length) : "5", label: "platforms" },
              { val: activeProfile?.industry_niche ? activeProfile.industry_niche.split(" ").slice(0, 2).join(" ") : "All niches", label: "niche" },
            ].map((s) => (
              <div key={s.label} className="rounded-xl bg-white border border-gray-100 px-4 py-3">
                <p className="text-xl font-bold text-indigo-600 leading-none">{s.val}</p>
                <p className="text-xs text-gray-400 mt-1">{s.label}</p>
              </div>
            ))}
          </div>
        )}

        {/* Profile tabs */}
        {profiles.length > 0 && (
          <div className="mb-6 flex items-center gap-2 overflow-x-auto pb-1">
            <LayoutList className="h-4 w-4 text-gray-400 shrink-0" />
            {profiles.map((p) => {
              const isActive = searchParams.profile
                ? p.id === searchParams.profile
                : p.id === profiles[0]?.id;
              return (
                <Link
                  key={p.id}
                  href={`/dashboard?profile=${p.id}`}
                  className={`shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                    isActive
                      ? "bg-blue-600 text-white"
                      : "bg-white border border-gray-200 text-gray-600 hover:border-blue-300 hover:text-blue-600"
                  }`}
                >
                  {p.name}
                </Link>
              );
            })}
            {activeProfile && (
              <span className="text-xs text-gray-400 ml-1 shrink-0">
                · {activeProfile.industry_niche}
              </span>
            )}
          </div>
        )}

        {/* No data state */}
        {!digest && (
          <div className="rounded-2xl border-2 border-dashed border-gray-200 py-20 text-center">
            <Inbox className="h-10 w-10 text-gray-300 mx-auto mb-4" />
            <h3 className="font-semibold text-gray-700 mb-2">Your first digest is on its way</h3>
            <p className="text-sm text-gray-400 max-w-xs mx-auto">
              The AI pipeline runs every morning at 7 AM. Your first personalized digest will arrive
              tomorrow. Hit &ldquo;Refresh&rdquo; to generate one now.
            </p>
          </div>
        )}

        {digest && (
          <div className="space-y-8">
            {/* Trend clusters */}
            {digest.clusters && digest.clusters.length > 0 && (
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <TrendingUp className="h-4 w-4 text-blue-600" />
                  <h2 className="text-base font-semibold text-gray-900">Today&apos;s top trends</h2>
                </div>
                <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {digest.clusters.slice(0, 6).map((c, i) => (
                    <div key={i} className="rounded-xl bg-white border border-gray-100 p-4">
                      <p className="font-semibold text-sm text-gray-900 mb-1">{c.name}</p>
                      <p className="text-xs text-gray-500 line-clamp-2">{c.description}</p>
                      {c.emotional_theme && (
                        <span className="mt-2 inline-block rounded-full bg-blue-50 text-blue-600 text-xs px-2 py-0.5">
                          {c.emotional_theme}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Content ideas */}
            {digest.content_ideas && digest.content_ideas.length > 0 && (
              <section>
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-base font-semibold text-gray-900">
                    {digest.content_ideas.length} posting proposals for today
                  </h2>
                  <span className="text-xs text-gray-400">Click any field or &ldquo;Copy full post&rdquo; to copy</span>
                </div>
                <div className="grid sm:grid-cols-2 gap-4">
                  {digest.content_ideas.map((idea, i) => (
                    <DigestCard key={i} idea={idea} index={i} contentId={digest.id} plan={plan} />
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

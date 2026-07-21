import { redirect } from "next/navigation";
import Link from "next/link";
import { TrendingUp, Inbox, LayoutList } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import AppNav from "@/components/AppNav";
import TrendIdeaCard from "@/components/TrendIdeaCard";
import RefreshButton from "@/components/RefreshButton";
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

async function fetchConnectedPlatforms(userId: string, activeProfileId?: string): Promise<string[]> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || RAILWAY;
  try {
    const res = await fetch(`${apiUrl}/api/social/accounts?user_id=${userId}`, { cache: "no-store" });
    if (!res.ok) return [];
    const data: { platform: string; status: string; content_profile_id: string | null }[] = await res.json();
    // Scoped to the active profile's own dedicated account, or a legacy
    // (unbound) account — mirrors app/social/service.py's resolve_active_account
    // fallback. Without this, a profile with no account of its own would still
    // show Publish/Track buttons just because a DIFFERENT profile has one.
    return data
      .filter(a => a.status === "active" && (a.content_profile_id === activeProfileId || a.content_profile_id === null))
      .map(a => a.platform);
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

  const profiles = await fetchProfiles(user.id);
  // Single source of truth for "needs onboarding" — a user with zero content
  // profiles has never completed the wizard (or their session outlived it),
  // so send them there instead of showing a permanently-empty dashboard.
  if (profiles.length === 0) redirect("/onboarding");

  const activeProfile = profiles.find((p) => p.id === searchParams.profile) ?? profiles[0] ?? null;

  const [digest, connectedPlatforms] = await Promise.all([
    fetchDigest(user.id, searchParams.profile),
    fetchConnectedPlatforms(user.id, activeProfile?.id),
  ]);
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });

  return (
    <div className="min-h-screen bg-gray-50">
      <AppNav active="dashboard" isSuperAdmin={isSuperAdmin} />

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
          <div>
            <p className="text-sm text-gray-500 mb-1">{today}</p>
            <h1 className="text-2xl font-bold text-gray-900">Your daily content brief</h1>
            {digest?.generated_at && (
              <p className="text-xs text-gray-400 mt-1">
                Generated {new Date(digest.generated_at).toLocaleTimeString()}
              </p>
            )}
          </div>
          <RefreshButton profileId={searchParams.profile} />
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

        {/* Trends + their connected content, side by side — the top 3 (most
            relevant) trends already have an idea generated; the rest show a
            Generate button so nothing is created unless actually wanted.
            digest.clusters is the set that fed this specific profile's ideas
            (not a disconnected global admin view) — was previously shown as
            plain info cards with no link to the ideas list below it, which is
            exactly the disconnect this replaces. */}
        {digest?.clusters && digest.clusters.length > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-4">
              <TrendingUp className="h-4 w-4 text-blue-600" />
              <h2 className="text-base font-semibold text-gray-900">Trending right now</h2>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 items-start">
              {digest.clusters.map((cluster, i) => {
                const existingIdeaIndex = digest.content_ideas?.findIndex((idea) => idea.cluster_index === i) ?? -1;
                const existingIdea = existingIdeaIndex >= 0 ? digest.content_ideas[existingIdeaIndex] : null;
                return (
                  <TrendIdeaCard
                    key={i}
                    cluster={cluster}
                    clusterIndex={i}
                    existingIdea={existingIdea}
                    existingIdeaIndex={existingIdeaIndex >= 0 ? existingIdeaIndex : null}
                    contentId={digest.id}
                    plan={plan}
                    connectedPlatforms={connectedPlatforms}
                    publishMode={activeProfile?.publish_mode ?? "manual"}
                  />
                );
              })}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

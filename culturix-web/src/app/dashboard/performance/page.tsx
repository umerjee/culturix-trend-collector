import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import AppNav from "@/components/AppNav";
import { Eye, Heart, MessageCircle, ExternalLink, BarChart3 } from "lucide-react";
import type { ContentPost } from "@/lib/types";

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

async function fetchContentPosts(userId: string): Promise<ContentPost[]> {
  try {
    const res = await fetch(`${RAILWAY}/api/content-posts?user_id=${userId}`, { cache: "no-store" });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

const PLATFORM_COLORS: Record<string, string> = {
  youtube: "bg-red-100 text-red-700",
  tiktok: "bg-pink-100 text-pink-700",
  twitter: "bg-sky-100 text-sky-700",
  instagram: "bg-purple-100 text-purple-700",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "Publishing…",
  fetching: "Updating…",
  tracked: "Tracked",
  failed: "Failed",
  needs_reconnect: "Reconnect needed",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default async function PerformancePage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

  const isSuperAdmin = user.email === "umer.ali79@gmail.com";
  const posts = await fetchContentPosts(user.id);
  const totalViews = posts.reduce((sum, p) => sum + (p.latest_views ?? 0), 0);

  return (
    <div className="min-h-screen bg-gray-50">
      <AppNav active="performance" isSuperAdmin={isSuperAdmin} />

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Performance</h1>
          <p className="text-sm text-gray-500 mt-1">
            Every idea you&apos;ve posted or published, and how it&apos;s actually doing.
          </p>
        </div>

        {posts.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
            {[
              { val: String(posts.length), label: "posts tracked" },
              { val: totalViews.toLocaleString(), label: "total views" },
              { val: String(posts.filter(p => p.created_via === "published").length), label: "published by Culturix" },
              { val: String(posts.filter(p => p.status === "tracked").length), label: "live & tracked" },
            ].map((s) => (
              <div key={s.label} className="rounded-xl bg-white border border-gray-100 px-4 py-3">
                <p className="text-xl font-bold text-indigo-600 leading-none">{s.val}</p>
                <p className="text-xs text-gray-400 mt-1">{s.label}</p>
              </div>
            ))}
          </div>
        )}

        {posts.length === 0 ? (
          <div className="rounded-2xl border-2 border-dashed border-gray-200 py-20 text-center">
            <BarChart3 className="h-10 w-10 text-gray-300 mx-auto mb-4" />
            <h3 className="font-semibold text-gray-700 mb-2">No posts tracked yet</h3>
            <p className="text-sm text-gray-400 max-w-sm mx-auto">
              Connect an account in Settings, then mark an idea as posted or publish one directly from
              your dashboard — results will show up here.
            </p>
          </div>
        ) : (
          <div className="rounded-2xl bg-white border border-gray-100 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-xs text-gray-400">
                    <th className="px-4 py-3 font-medium">Idea</th>
                    <th className="px-4 py-3 font-medium">Platform</th>
                    <th className="px-4 py-3 font-medium">Posted</th>
                    <th className="px-4 py-3 font-medium">Views</th>
                    <th className="px-4 py-3 font-medium">Likes</th>
                    <th className="px-4 py-3 font-medium">Comments</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {posts.map((p) => (
                    <tr key={p.id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50">
                      <td className="px-4 py-3 max-w-xs truncate text-gray-900">{p.hook ?? "—"}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-semibold rounded-full px-2.5 py-1 capitalize ${PLATFORM_COLORS[p.platform] ?? "bg-gray-100 text-gray-700"}`}>
                          {p.platform}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-500">{formatDate(p.posted_at)}</td>
                      <td className="px-4 py-3 text-gray-700">
                        {p.latest_views != null ? (
                          <span className="flex items-center gap-1"><Eye className="h-3.5 w-3.5 text-gray-400" />{p.latest_views.toLocaleString()}</span>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-3 text-gray-700">
                        {p.latest_likes != null ? (
                          <span className="flex items-center gap-1"><Heart className="h-3.5 w-3.5 text-gray-400" />{p.latest_likes.toLocaleString()}</span>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-3 text-gray-700">
                        {p.latest_comments != null ? (
                          <span className="flex items-center gap-1"><MessageCircle className="h-3.5 w-3.5 text-gray-400" />{p.latest_comments.toLocaleString()}</span>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400">{STATUS_LABEL[p.status] ?? p.status}</td>
                      <td className="px-4 py-3">
                        {p.post_url && (
                          <a href={p.post_url} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:text-blue-600">
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

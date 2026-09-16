import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { isSuperAdminEmail } from "@/lib/admin/superadmin";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import { internalApiHeaders } from "@/lib/internalApiHeaders";
import AppNav from "@/components/AppNav";
import EmptyState from "@/components/ui/EmptyState";
import { CalendarDays } from "lucide-react";

interface CalendarEvent {
  id: number;
  name: string;
  category: string;
  date: string;
  regions: string[];
  description: string | null;
}

async function fetchUpcomingEvents(userId: string, category?: string): Promise<CalendarEvent[]> {
  try {
    const params = new URLSearchParams({ user_id: userId, lookahead_days: "120" });
    if (category) params.set("category", category);
    const res = await fetch(`${RAILWAY_API_BASE}/api/calendar-events?${params.toString()}`, {
      cache: "no-store",
      headers: internalApiHeaders(),
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

const CATEGORY_STYLE: Record<string, string> = {
  holiday: "bg-emerald-100 text-emerald-700",
  religious: "bg-purple-100 text-purple-700",
  political: "bg-red-100 text-red-700",
  sports: "bg-blue-100 text-blue-700",
  music: "bg-pink-100 text-pink-700",
};

const CATEGORIES = ["holiday", "religious", "political", "sports", "music"];

function formatEventDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00Z");
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
}

export default async function CalendarPage({ searchParams }: { searchParams: { category?: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

  const isSuperAdmin = isSuperAdminEmail(user.email);
  const activeCategory = CATEGORIES.includes(searchParams.category ?? "") ? searchParams.category : undefined;
  const events = await fetchUpcomingEvents(user.id, activeCategory);

  return (
    <>
      <AppNav active="calendar" isSuperAdmin={isSuperAdmin} product="posting-ideation" />

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Calendar</h1>
          <p className="text-sm text-gray-500 mt-1">
            Upcoming holidays, religious observances, political events, sports, and music — scoped to your content
            profiles&apos; target regions, so you can plan content ahead of what&apos;s actually coming.
          </p>
        </div>

        <div className="flex items-center gap-2 mb-6 flex-wrap">
          <Link
            href="/dashboard/calendar"
            className={`text-xs font-medium rounded-full px-3 py-1.5 border transition-colors ${
              !activeCategory ? "bg-gray-900 text-white border-gray-900" : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
            }`}
          >
            All
          </Link>
          {CATEGORIES.map((c) => (
            <Link
              key={c}
              href={`/dashboard/calendar?category=${c}`}
              className={`text-xs font-medium rounded-full px-3 py-1.5 border capitalize transition-colors ${
                activeCategory === c ? "bg-gray-900 text-white border-gray-900" : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
              }`}
            >
              {c}
            </Link>
          ))}
        </div>

        {events.length === 0 ? (
          <EmptyState
            icon={CalendarDays}
            title="No upcoming events found"
            description="Either nothing is scheduled in the next 120 days for this filter, or your content profiles don't have target regions set yet — add some in Settings to scope this calendar to your audience."
          />
        ) : (
          <div className="rounded-2xl bg-white border border-gray-100 divide-y divide-gray-100 overflow-hidden">
            {events.map((e) => (
              <div key={e.id} className="flex items-center gap-3 px-4 py-3.5">
                <span className={`text-[10px] font-semibold uppercase tracking-wide rounded-full px-2 py-1 shrink-0 ${CATEGORY_STYLE[e.category] ?? "bg-gray-100 text-gray-700"}`}>
                  {e.category}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 truncate">{e.name}</p>
                  {e.description && <p className="text-xs text-gray-500 truncate">{e.description}</p>}
                </div>
                <span className="text-xs text-gray-400 whitespace-nowrap shrink-0 hidden sm:inline">
                  {e.regions.length > 0 ? e.regions.join(", ") : "Global"}
                </span>
                <span className="text-xs font-medium text-gray-600 whitespace-nowrap shrink-0">{formatEventDate(e.date)}</span>
              </div>
            ))}
          </div>
        )}
      </main>
    </>
  );
}

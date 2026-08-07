import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// Ranked by relevance to the brand's own trend_interests when set — see
// app/routers/culturetoons.py::get_trend_sources and
// app/services/culturetoon_trend_relevance.py. Used to be a client-side
// aggregation of the trend engine's generic /personas and /clusters
// endpoints with zero brand awareness; now a real backend route.
export async function GET(req: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const brandId = searchParams.get("brand_id");
  if (!brandId) return NextResponse.json({ detail: "brand_id is required" }, { status: 400 });

  const res = await fetch(`${RAILWAY}/api/culturetoons/trend-sources?user_id=${user.id}&brand_id=${brandId}`, {
    cache: "no-store",
    // Personalized ranking can trigger a Voyage embedding call on first
    // use for uncached candidates — same generous timeout as other
    // AI-generation proxy routes, not the default 15s.
    signal: AbortSignal.timeout(30000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

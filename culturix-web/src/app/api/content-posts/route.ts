import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// POST /api/content-posts  →  manual tracking: user posted this idea themselves, paste the link
export async function POST(req: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json();
  const res = await fetch(`${RAILWAY}/api/content-posts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, user_id: user.id }),
    signal: AbortSignal.timeout(15000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

// GET /api/content-posts[?content_profile_id=...]  →  aggregate feed for the
// Performance page, optionally scoped to one profile (used by the
// publishing-setup status view on the Dashboard and in Settings).
export async function GET(req: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const profileId = searchParams.get("content_profile_id");
  const qs = profileId ? `&content_profile_id=${profileId}` : "";

  const res = await fetch(`${RAILWAY}/api/content-posts?user_id=${user.id}${qs}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(15000),
  });
  const data = await res.json().catch(() => []);
  return NextResponse.json(data, { status: res.status });
}

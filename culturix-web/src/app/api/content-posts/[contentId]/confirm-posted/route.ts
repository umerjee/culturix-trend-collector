import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// POST /api/content-posts/[contentId]/confirm-posted  →  { post_url }
// User published the staged content themselves; hands off into the existing
// manual-tracking pipeline (fetch_and_record) on the backend.
export async function POST(
  req: Request,
  { params }: { params: { contentId: string } }
) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json();
  const res = await fetch(
    `${RAILWAY}/api/content-posts/${params.contentId}/confirm-posted`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    }
  );
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

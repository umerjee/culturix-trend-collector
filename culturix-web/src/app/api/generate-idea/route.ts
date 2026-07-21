import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// POST /api/generate-idea  →  { content_id, cluster_index } — on-demand, one-time
// content generation for a single trend that wasn't in the automatic top 3.
export async function POST(req: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json();
  const res = await fetch(`${RAILWAY}/api/generate-idea`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(30000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

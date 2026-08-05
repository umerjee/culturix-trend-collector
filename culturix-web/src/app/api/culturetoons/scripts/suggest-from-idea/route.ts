import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

export async function POST(req: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const res = await fetch(`${RAILWAY}/api/culturetoons/scripts/suggest-from-idea`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, user_id: user.id }),
    // LLM call — matches the 30000ms convention used for scripts/suggest.
    signal: AbortSignal.timeout(30000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

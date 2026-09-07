import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// See scripts/suggest/route.ts's comment for why this is explicit and why
// it moved past 60s (2026-09-07).
export const maxDuration = 120;

export async function POST(req: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  try {
    // Two sequential LLM calls — see scripts/suggest/route.ts's comment.
    const res = await fetch(`${RAILWAY}/api/culturetoons/scripts/suggest-from-idea`, {
      method: "POST",
      headers: internalApiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ ...body, user_id: user.id }),
      signal: AbortSignal.timeout(115000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Script generation timed out — try again." }, { status: 504 });
  }
}

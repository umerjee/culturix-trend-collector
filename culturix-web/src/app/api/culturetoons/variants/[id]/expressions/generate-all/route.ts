import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

export async function POST(req: Request, { params }: { params: { id: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  try {
    // Up to 10 sequential image-generation calls (one per missing
    // expression) — the single-expression route's 30000ms convention is
    // sized for ONE call, not ten, so this needs real headroom.
    const res = await fetch(`${RAILWAY}/api/culturetoons/variants/${params.id}/expressions/generate-all`, {
      method: "POST",
      headers: internalApiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ ...body, user_id: user.id }),
      signal: AbortSignal.timeout(180000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Generating expressions timed out — some may have completed, check below and retry any missing ones." }, { status: 504 });
  }
}

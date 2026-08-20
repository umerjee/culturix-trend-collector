import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

export async function POST(req: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  try {
    // Two sequential LLM calls now, not one — the backend writes the
    // script, then judge_script_comedy() scores it in a separate call
    // before returning. 30000ms was sized for the single call and was
    // cutting this off mid-request (confirmed live: "Suggestion failed"
    // with no real backend error, just an aborted fetch with nothing
    // caught here to surface a proper message).
    const res = await fetch(`${RAILWAY}/api/culturetoons/scripts/suggest`, {
      method: "POST",
      headers: internalApiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ ...body, user_id: user.id }),
      signal: AbortSignal.timeout(60000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Script generation timed out — try again." }, { status: 504 });
  }
}

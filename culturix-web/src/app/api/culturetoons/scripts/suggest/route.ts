import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// Explicit, not left to Next.js/Vercel's implicit platform default — the
// AbortSignal below only protects against a hung fetch INSIDE this
// function; if the platform's own execution limit is shorter, the whole
// function gets killed first regardless of what the AbortSignal says.
// Raised 60s -> 120s 2026-09-07: the script-generation prompt grew
// substantially that session (anti-copying guidance, a new per-shot
// location field, dialogue-rhythm guidance), and a live-timed run of the
// two-sequential-LLM-call path (write, then judge) came in at 48.4s —
// comfortable under the old 60s bound on a good run, but with too little
// margin against real latency variance, confirmed live as "script
// generation timed out" reports right after that prompt work shipped.
export const maxDuration = 120;

export async function POST(req: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  try {
    // Two sequential LLM calls — the backend writes the script, then
    // judge_script_comedy() scores it in a separate call before returning.
    // See maxDuration's comment above for why this needs real headroom.
    const res = await fetch(`${RAILWAY}/api/culturetoons/scripts/suggest`, {
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

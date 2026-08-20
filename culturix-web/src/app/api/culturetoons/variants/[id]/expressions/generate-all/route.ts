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
    // Backgrounded on the backend (see CharacterVariant.expressions_
    // generating's docstring) — this call just flips a flag and kicks off
    // a background task, so it returns almost instantly. A synchronous
    // version of this ran 10 sequential image-generation calls inline and
    // got killed mid-batch by Vercel's own serverless function execution
    // limit — don't revert to a long AbortSignal here as a "fix", that
    // doesn't address the real constraint.
    const res = await fetch(`${RAILWAY}/api/culturetoons/variants/${params.id}/expressions/generate-all`, {
      method: "POST",
      headers: internalApiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ ...body, user_id: user.id }),
      signal: AbortSignal.timeout(30000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Couldn't start generation — try again." }, { status: 504 });
  }
}

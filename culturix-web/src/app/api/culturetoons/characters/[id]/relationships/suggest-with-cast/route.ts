import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// Drafts a relationship between this character and every other active
// character in the cast, one AI call per pair — see
// app/routers/culturetoons.py::suggest_relationships_with_cast. Longer
// timeout than the single-pair .../relationships/generate proxy since a
// cast of N other characters means N sequential LLM calls server-side.
export async function POST(req: Request, { params }: { params: { id: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const res = await fetch(`${RAILWAY}/api/culturetoons/characters/${params.id}/relationships/suggest-with-cast`, {
    method: "POST",
    headers: internalApiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ ...body, user_id: user.id }),
    signal: AbortSignal.timeout(60000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

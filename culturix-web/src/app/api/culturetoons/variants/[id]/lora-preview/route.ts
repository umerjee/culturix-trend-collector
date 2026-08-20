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
    // Backgrounded on the backend (see CharacterVariant.lora_preview_url's
    // docstring) — this call just flips a status flag and kicks off a
    // background task, so it returns almost instantly. The actual
    // Serverless generation is polled via the variant, same pattern as
    // /expressions/generate-all.
    const res = await fetch(`${RAILWAY}/api/culturetoons/variants/${params.id}/lora-preview`, {
      method: "POST",
      headers: internalApiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ ...body, user_id: user.id }),
      signal: AbortSignal.timeout(30000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Couldn't start preview generation — try again." }, { status: 504 });
  }
}

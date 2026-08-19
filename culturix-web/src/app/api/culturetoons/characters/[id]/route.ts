import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

export async function PUT(req: Request, { params }: { params: { id: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const res = await fetch(`${RAILWAY}/api/culturetoons/characters/${params.id}`, {
    method: "PUT",
    headers: internalApiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ ...body, user_id: user.id }),
    signal: AbortSignal.timeout(15000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

// Was missing entirely -- archiveCharacter() in CharacterVariantManager.tsx
// has been calling this route with method "DELETE" since that feature
// shipped, but with no DELETE export here Next.js 405s it before the
// request ever reaches Railway. Confirmed live: silently did nothing from
// the user's side, since the caller only handles the res.ok case.
export async function DELETE(req: Request, { params }: { params: { id: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const brandId = searchParams.get("brand_id");
  if (!brandId) return NextResponse.json({ detail: "brand_id is required" }, { status: 400 });

  const target = new URL(`${RAILWAY}/api/culturetoons/characters/${params.id}`);
  target.searchParams.set("user_id", user.id);
  target.searchParams.set("brand_id", brandId);

  const res = await fetch(target.toString(), {
    method: "DELETE",
    headers: internalApiHeaders(),
    signal: AbortSignal.timeout(15000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

export async function DELETE(req: Request, { params }: { params: { id: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const brandId = searchParams.get("brand_id");
  if (!brandId) return NextResponse.json({ detail: "brand_id is required" }, { status: 400 });

  const res = await fetch(`${RAILWAY}/api/culturetoons/relationship-events/${params.id}?user_id=${user.id}&brand_id=${brandId}`, {
    headers: internalApiHeaders(),
    method: "DELETE",
    signal: AbortSignal.timeout(15000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

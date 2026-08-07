import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

export async function POST(req: Request, { params }: { params: { id: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const incoming = await req.formData();
  const file = incoming.get("file");
  const brandId = incoming.get("brand_id");
  if (!file) return NextResponse.json({ detail: "file is required" }, { status: 400 });
  if (!brandId) return NextResponse.json({ detail: "brand_id is required" }, { status: 400 });

  const forward = new FormData();
  forward.set("user_id", user.id);
  forward.set("brand_id", brandId);
  forward.set("file", file);

  const res = await fetch(`${RAILWAY}/api/culturetoons/backgrounds/${params.id}/reference-images`, {
    method: "POST",
    body: forward,
    signal: AbortSignal.timeout(30000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

export async function DELETE(req: Request, { params }: { params: { id: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const brandId = searchParams.get("brand_id");
  const imageUrl = searchParams.get("image_url");
  if (!brandId) return NextResponse.json({ detail: "brand_id is required" }, { status: 400 });
  if (!imageUrl) return NextResponse.json({ detail: "image_url is required" }, { status: 400 });

  const qs = new URLSearchParams({ user_id: user.id, brand_id: brandId, image_url: imageUrl });
  const res = await fetch(`${RAILWAY}/api/culturetoons/backgrounds/${params.id}/reference-images?${qs.toString()}`, {
    method: "DELETE",
    signal: AbortSignal.timeout(15000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

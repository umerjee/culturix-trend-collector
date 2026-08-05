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
  if (!file) return NextResponse.json({ detail: "file is required" }, { status: 400 });

  const forward = new FormData();
  forward.set("user_id", user.id);
  forward.set("file", file);

  const res = await fetch(`${RAILWAY}/api/culturetoons/characters/${params.id}/image`, {
    method: "POST",
    body: forward,
    signal: AbortSignal.timeout(30000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

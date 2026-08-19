import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// PublishingWizard.tsx (the trend engine's own connect-test-mode wizard,
// distinct from CultureToons' equivalent at
// api/culturetoons/social/[platform]/test) used to call Railway directly
// from the browser. That can't carry INTERNAL_API_SECRET at all -- a
// client component has no server secret to send -- so once
// /api/social/{platform}/test was gated, this call started failing
// outright. Routes it through this server-side proxy instead, same
// pattern as every other Next -> Railway call.
export async function POST(req: Request, { params }: { params: { platform: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const contentProfileId = searchParams.get("content_profile_id");

  const target = new URL(`${RAILWAY}/api/social/${params.platform}/test`);
  target.searchParams.set("user_id", user.id);
  if (contentProfileId) target.searchParams.set("content_profile_id", contentProfileId);

  const res = await fetch(target.toString(), {
    method: "POST",
    headers: internalApiHeaders(),
    signal: AbortSignal.timeout(20000),
  });
  const data = await res.json().catch(() => ({ ok: false }));
  return NextResponse.json(data, { status: res.status });
}

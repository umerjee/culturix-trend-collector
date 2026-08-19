import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// SettingsForm.tsx used to call Railway directly from the browser for
// this. Proxies server-side instead, same pattern as every other Next ->
// Railway call.
export async function DELETE(req: Request, { params }: { params: { platform: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const contentProfileId = searchParams.get("content_profile_id");

  const target = new URL(`${RAILWAY}/api/social/${params.platform}/disconnect`);
  target.searchParams.set("user_id", user.id);
  if (contentProfileId) target.searchParams.set("content_profile_id", contentProfileId);

  const res = await fetch(target.toString(), { method: "DELETE", headers: internalApiHeaders() });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

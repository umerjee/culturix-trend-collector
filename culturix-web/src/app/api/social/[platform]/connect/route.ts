import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

export async function GET(req: Request, { params }: { params: { platform: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.redirect(new URL("/signup", req.url));

  const input = new URL(req.url).searchParams;
  const profileId = input.get("content_profile_id");
  if (!profileId) return NextResponse.json({ detail: "content_profile_id is required" }, { status: 400 });

  const target = new URL(`${RAILWAY_API_BASE}/api/social/${params.platform}/connect`);
  target.searchParams.set("user_id", user.id);
  target.searchParams.set("content_profile_id", profileId);
  const response = await fetch(target, {
    headers: internalApiHeaders(),
    redirect: "manual",
    cache: "no-store",
  });
  const location = response.headers.get("location");
  if (response.status >= 300 && response.status < 400 && location) {
    return NextResponse.redirect(location);
  }
  return NextResponse.json({ detail: "Could not start OAuth connection" }, { status: response.status || 502 });
}

import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

// Browser-navigable (an <a href>, not a fetch) — redirects on to Railway's
// own OAuth-initiating redirect, which redirects again to the platform's
// consent screen. Resolves user_id server-side from the Supabase session
// rather than trusting a client-supplied id, matching every other
// CultureToons proxy route (unlike PublishingWizard.tsx's older pattern of
// linking straight to Railway with a client-held userId).
export async function GET(req: Request, { params }: { params: { platform: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.redirect(new URL("/login", req.url));

  const { searchParams } = new URL(req.url);
  const brandId = searchParams.get("brand_id");
  if (!brandId) return NextResponse.json({ detail: "brand_id is required" }, { status: 400 });

  const target = new URL(`${RAILWAY_API_BASE}/api/social/${params.platform}/connect`);
  target.searchParams.set("user_id", user.id);
  target.searchParams.set("character_brand_id", brandId);
  const response = await fetch(target, { headers: internalApiHeaders(), redirect: "manual", cache: "no-store" });
  const location = response.headers.get("location");
  if (response.status >= 300 && response.status < 400 && location) return NextResponse.redirect(location);
  return NextResponse.json({ detail: "Could not start OAuth connection" }, { status: response.status || 502 });
}

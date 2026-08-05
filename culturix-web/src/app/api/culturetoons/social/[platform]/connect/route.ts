import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

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

  return NextResponse.redirect(
    `${RAILWAY}/api/social/${params.platform}/connect?user_id=${user.id}&character_brand_id=${brandId}`,
  );
}

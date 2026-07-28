import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// GET /api/shopify/connect?shop_domain=... — injects the authenticated
// user's id server-side (never exposed to the client) before handing off
// to Railway's OAuth authorize redirect.
export async function GET(req: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.redirect(new URL("/login", req.url));

  const shopDomain = new URL(req.url).searchParams.get("shop_domain");
  if (!shopDomain) {
    return NextResponse.json({ error: "shop_domain is required" }, { status: 400 });
  }

  const target = new URL(`${RAILWAY}/api/shopify/connect`);
  target.searchParams.set("user_id", user.id);
  target.searchParams.set("shop_domain", shopDomain);
  return NextResponse.redirect(target);
}

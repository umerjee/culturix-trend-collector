import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// SettingsForm.tsx re-checks approval/plan status client-side (to pick up
// a just-completed Stripe checkout redirect before the webhook-driven
// server value would) by calling Railway directly, which can't carry
// INTERNAL_API_SECRET. Proxies server-side instead, resolving user_id
// from the verified session same as /api/profile.
export async function GET() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const res = await fetch(`${RAILWAY}/api/users/${user.id}/approved`, {
    cache: "no-store",
    headers: internalApiHeaders(),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

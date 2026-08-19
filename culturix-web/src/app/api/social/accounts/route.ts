import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// SettingsForm.tsx (the trend engine's own connected-accounts panel) used
// to call Railway directly from the browser, which can't carry
// INTERNAL_API_SECRET at all. Proxies server-side instead, same pattern
// as every other Next -> Railway call.
export async function GET() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const res = await fetch(`${RAILWAY}/api/social/accounts?user_id=${user.id}`, {
    cache: "no-store",
    headers: internalApiHeaders(),
  });
  const data = await res.json().catch(() => []);
  return NextResponse.json(data, { status: res.status });
}

import { createClient } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const type = searchParams.get("type");
  const next = searchParams.get("next") ?? (type === "recovery" ? "/reset-password" : "/dashboard");

  if (code) {
    const supabase = createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  // Recovery links that fail here (expired, already used, or the domain isn't
  // in Supabase's Auth > URL Configuration redirect allowlist) are most
  // usefully resolved by requesting a fresh one, not by landing on signup.
  const failureTarget = type === "recovery" ? "/forgot-password" : "/signup";
  return NextResponse.redirect(`${origin}${failureTarget}?error=auth_callback_failed`);
}

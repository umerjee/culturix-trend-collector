import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

export async function POST(req: Request) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  // Read profile_id from form data (optional)
  let profileId: string | null = null;
  try {
    const form = await req.formData();
    profileId = form.get("profile_id") as string | null;
  } catch {
    // JSON body or no body — profile_id not required
  }

  const redirectUrl = profileId
    ? new URL(`/dashboard?profile=${profileId}`, req.url)
    : new URL("/dashboard", req.url);

  try {
    await fetch(`${RAILWAY}/api/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: user.id }),
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    // Pipeline started async on Railway — timeout is expected, not an error
  }

  return NextResponse.redirect(redirectUrl);
}

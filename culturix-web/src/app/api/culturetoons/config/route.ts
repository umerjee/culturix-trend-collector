import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { internalApiHeaders } from "@/lib/internalApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// Which video renderer this deployment runs, and what it actually requires
// of a character — see app/routers/culturetoons.py::get_video_config.
//
// Every backend endpoint needs an explicit proxy route here; there is no
// catch-all. Without this file `fetch("/api/culturetoons/config")` 404s, the
// components fall back to their pre-LTX-2.5 layout, and the UI goes on
// demanding Kling registration and LoRA training that the renderer never
// reads — which is exactly what happened when this route was missed.
//
// Brand-independent and carries no user data, but still gated on a session
// like every other route here: the backend refuses unauthenticated calls
// (a direct request returns 403), so this must go through internalApiHeaders.
export async function GET() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const res = await fetch(`${RAILWAY}/api/culturetoons/config`, {
    headers: internalApiHeaders(),
    cache: "no-store",
    signal: AbortSignal.timeout(15000),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

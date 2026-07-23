import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// GET /api/content-profiles/:id/persona-advisory → which of this profile's
// persona_tags are currently declining/dormant (see main.py's
// persona_advisory route). Powers the Dashboard's PersonaAdvisory banner.
export async function GET(_req: Request, { params }: { params: { id: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const res = await fetch(
    `${RAILWAY}/users/${user.id}/content-profiles/${params.id}/persona-advisory`,
    { cache: "no-store" }
  );
  const data = await res.json().catch(() => ({ declining: [], dormant: [] }));
  return NextResponse.json(data, { status: res.status });
}

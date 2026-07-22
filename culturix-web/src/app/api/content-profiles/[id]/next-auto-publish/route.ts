import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// GET /api/content-profiles/:id/next-auto-publish → read-only preview of what
// run_auto_publish() would post next for this profile (auto mode only).
export async function GET(_req: Request, { params }: { params: { id: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const res = await fetch(
    `${RAILWAY}/users/${user.id}/content-profiles/${params.id}/next-auto-publish`,
    { cache: "no-store" }
  );
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

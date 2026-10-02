import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireSuperAdminApi } from "./requireSuperAdminApi";
import { adminApiHeaders } from "./adminApiHeaders";

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

// POST proxy for /admin/editorial/* (app/routers/editorial.py). Adds, server-side only, the
// reviewer's email (audit trail) and, when `withUserId`, the admin's own Supabase id, which owns
// the CultureToons brands and cast used to write a script. Neither is ever taken from the browser.
export async function forwardEditorialPost(req: Request, path: string, opts: { withUserId?: boolean; timeoutMs?: number } = {}) {
  const gate = await requireSuperAdminApi();
  if (gate instanceof NextResponse) return gate;
  const body = await req.json().catch(() => ({}));
  const extra: Record<string, string> = { reviewer: gate.email };
  if (opts.withUserId) {
    const { data: { user } } = await createClient().auth.getUser();
    if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    extra.user_id = user.id;
  }
  try {
    const res = await fetch(`${RAILWAY}/admin/editorial/${path}`, {
      method: "POST",
      headers: adminApiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ ...body, ...extra }),
      signal: AbortSignal.timeout(opts.timeoutMs ?? 30000),
    });
    return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
  } catch (e) {
    return NextResponse.json({ detail: `Backend unreachable: ${String(e)}` }, { status: 502 });
  }
}

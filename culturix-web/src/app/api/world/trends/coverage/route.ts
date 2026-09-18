import { NextResponse } from "next/server";
import { RAILWAY_API_BASE } from "@/lib/config/api";

// GET /api/world/trends/coverage → real earliest/latest/days_with_data for
// one region, powers TimeCursor's honest sizing of its "recent" zone.
// Public — no auth needed, same as /api/regions (see that route's own note).
export async function GET(req: Request) {
  const { search } = new URL(req.url);
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/trends/coverage${search}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

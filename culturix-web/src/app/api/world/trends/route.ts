import { NextResponse } from "next/server";
import { RAILWAY_API_BASE } from "@/lib/config/api";

// GET /api/world/trends → real trend data by region, powers the "Trending
// in {region}" section on /world/region/[code]. Public — no auth needed,
// same as /api/regions (see that route's own note).
export async function GET(req: Request) {
  const { search } = new URL(req.url);
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/trends${search}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

import { NextResponse } from "next/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// GET /api/regions → canonical target-region catalog, powers RegionChips.tsx.
// Public — no auth needed, same as /api/personas/active.
export async function GET() {
  try {
    const res = await fetch(`${RAILWAY}/regions`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const data = await res.json().catch(() => []);
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

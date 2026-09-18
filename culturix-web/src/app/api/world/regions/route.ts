import { NextResponse } from "next/server";
import { RAILWAY_API_BASE } from "@/lib/config/api";

// GET /api/world/regions → which regions actually have ready World content
// (with a count each), powers WorldMap.tsx's choropleth. Public — no auth
// needed, same as /api/regions (a different, full-catalog endpoint — see
// that route's own note).
export async function GET() {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/regions`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const data = await res.json().catch(() => ({ regions: [] }));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

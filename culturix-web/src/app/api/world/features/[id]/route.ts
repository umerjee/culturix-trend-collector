import { NextResponse } from "next/server";
import { RAILWAY_API_BASE } from "@/lib/config/api";

// GET /api/world/features/:id → single World Feature detail, powers the
// /world/feature/[id] player page. Public — no auth needed, same as
// /api/regions (see that route's own note).
export async function GET(_req: Request, { params }: { params: { id: string } }) {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/features/${params.id}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

import { NextResponse } from "next/server";
import { RAILWAY_API_BASE } from "@/lib/config/api";

// GET /api/world/regions/{code}/summary?date=&lang= → cached daily brief for a country.
export async function GET(req: Request, { params }: { params: { code: string } }) {
  const { search } = new URL(req.url);
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/regions/${encodeURIComponent(params.code)}/summary${search}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(30000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

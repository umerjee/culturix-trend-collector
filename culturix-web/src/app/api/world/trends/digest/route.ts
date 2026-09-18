import { NextResponse } from "next/server";
import { RAILWAY_API_BASE } from "@/lib/config/api";

// GET /api/world/trends/digest → grouped, human-readable trend context.
export async function GET(req: Request) {
  const { search } = new URL(req.url);
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/trends/digest${search}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
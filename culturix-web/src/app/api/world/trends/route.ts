import { NextResponse } from "next/server";
import { RAILWAY_API_BASE } from "@/lib/config/api";

// GET /api/world/trends and /api/world/trends/digest → raw signals and their
// human-readable grouped interpretation for the World region page.
export async function GET(req: Request) {
  const { search } = new URL(req.url);
  try {
    const pathname = new URL(req.url).pathname;
    const endpoint = pathname.endsWith("/digest") ? "digest" : "";
    const res = await fetch(`${RAILWAY_API_BASE}/world/trends${endpoint ? `/${endpoint}` : ""}${search}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

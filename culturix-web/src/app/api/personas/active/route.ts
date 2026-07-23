import { NextResponse } from "next/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// GET /api/personas/active → live, momentum-tracked audience-tag catalog,
// powers PersonaChips.tsx's picker. Public — no auth needed, same as any
// other picker data (matches how PLATFORMS/REGIONS constants are used).
export async function GET() {
  try {
    const res = await fetch(`${RAILWAY}/personas/active`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const data = await res.json().catch(() => []);
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

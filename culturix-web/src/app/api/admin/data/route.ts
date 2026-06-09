import { NextResponse } from "next/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

const PATH_MAP: Record<string, string> = {
  trends:   "/admin/trends?limit=200",
  clusters: "/admin/clusters?limit=50",
  personas: "/admin/personas?limit=50",
  digests:  "/admin/digests?limit=20",
  users:    "/admin/users",
};

export async function GET(req: Request) {
  const type = new URL(req.url).searchParams.get("type") ?? "";
  const path = PATH_MAP[type];
  if (!path) return NextResponse.json({ error: "Invalid type" }, { status: 400 });

  try {
    const res = await fetch(`${RAILWAY}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

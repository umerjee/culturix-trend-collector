import { NextResponse } from "next/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

const PATH_MAP: Record<string, string> = {
  trends:        "/admin/trends?limit=200",
  clusters:      "/admin/clusters?limit=50",
  personas:      "/admin/personas?limit=50",
  digests:       "/admin/digests?limit=20",
  users:         "/admin/users",
  "trend-history": "/admin/trend-history?limit=100",
};

// Types that need an :id substituted into the backend path
const ID_PATH_MAP: Record<string, (id: string) => string> = {
  "cluster-detail":            (id) => `/clusters/${id}`,
  "persona-detail":            (id) => `/personas/${id}`,
  "trend-history-occurrences": (id) => `/admin/trend-history/${id}/occurrences?limit=200`,
  "persona-occurrences":       (id) => `/admin/personas/${id}/occurrences?limit=200`,
};

export async function GET(req: Request) {
  const url = new URL(req.url);
  const type = url.searchParams.get("type") ?? "";
  const id = url.searchParams.get("id");

  const path = id && ID_PATH_MAP[type] ? ID_PATH_MAP[type](id) : PATH_MAP[type];
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

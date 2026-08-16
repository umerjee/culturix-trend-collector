import { NextResponse } from "next/server";
import { requireSuperAdminApi } from "@/lib/admin/requireSuperAdminApi";
import { adminApiHeaders } from "@/lib/admin/adminApiHeaders";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

const PATH_MAP: Record<string, { path: string; defaultLimit?: number }> = {
  trends:                { path: "/admin/trends", defaultLimit: 200 },
  clusters:              { path: "/admin/clusters", defaultLimit: 50 },
  personas:              { path: "/admin/personas", defaultLimit: 50 },
  digests:               { path: "/admin/digests", defaultLimit: 20 },
  users:                 { path: "/admin/users" },
  "trend-history":       { path: "/admin/trend-history", defaultLimit: 100 },
  validation:            { path: "/admin/trend-validation-log", defaultLimit: 500 },
  stats:                 { path: "/admin/stats" },
  "integration-health":  { path: "/admin/integration-health" },
  "content-check-log":   { path: "/admin/content-check-log", defaultLimit: 100 },
  "high-velocity-alerts": { path: "/admin/high-velocity-alerts", defaultLimit: 50 },
};

// Types that need an :id substituted into the backend path
const ID_PATH_MAP: Record<string, (id: string) => string> = {
  "cluster-detail":            (id) => `/clusters/${id}`,
  "persona-detail":            (id) => `/personas/${id}`,
  "trend-history-occurrences": (id) => `/admin/trend-history/${id}/occurrences?limit=200`,
  "persona-occurrences":       (id) => `/admin/personas/${id}/occurrences?limit=200`,
};

export async function GET(req: Request) {
  const gate = await requireSuperAdminApi();
  if (gate instanceof NextResponse) return gate;

  const url = new URL(req.url);
  const type = url.searchParams.get("type") ?? "";
  const id = url.searchParams.get("id");
  const limitParam = url.searchParams.get("limit");

  let path: string | undefined;
  if (id && ID_PATH_MAP[type]) {
    path = ID_PATH_MAP[type](id);
  } else if (PATH_MAP[type]) {
    const entry = PATH_MAP[type];
    const limit = limitParam ?? entry.defaultLimit;
    path = limit ? `${entry.path}?limit=${limit}` : entry.path;
  }
  if (!path) return NextResponse.json({ error: "Invalid type" }, { status: 400 });

  try {
    const res = await fetch(`${RAILWAY}${path}`, {
      cache: "no-store",
      headers: adminApiHeaders(),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

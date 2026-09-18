import { NextResponse } from "next/server";
import { requireSuperAdminApi } from "@/lib/admin/requireSuperAdminApi";
import { adminApiHeaders } from "@/lib/admin/adminApiHeaders";

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

export async function POST(req: Request) {
  const gate = await requireSuperAdminApi();
  if (gate instanceof NextResponse) return gate;
  const body = await req.json();
  const res = await fetch(`${RAILWAY}/admin/curated-items/ingest`, {
    method: "POST", headers: adminApiHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(body),
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
import { NextResponse } from "next/server";
import { requireSuperAdminApi } from "@/lib/admin/requireSuperAdminApi";
import { adminApiHeaders } from "@/lib/admin/adminApiHeaders";

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

export async function POST(req: Request, { params }: { params: { id: string } }) {
  const gate = await requireSuperAdminApi();
  if (gate instanceof NextResponse) return gate;
  const body = await req.json().catch(() => ({}));
  const res = await fetch(`${RAILWAY}/admin/world-production/${params.id}/improve`, {
    method: "POST", headers: adminApiHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ note: body.note ?? null }),
  });
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}

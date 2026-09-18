import { NextResponse } from "next/server";
import { requireSuperAdminApi } from "@/lib/admin/requireSuperAdminApi";
import { adminApiHeaders } from "@/lib/admin/adminApiHeaders";

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

export async function POST(req: Request, { params }: { params: { id: string } }) {
  const gate = await requireSuperAdminApi();
  if (gate instanceof NextResponse) return gate;
  const decision = new URL(req.url).searchParams.get("decision") || "";
  const res = await fetch(`${RAILWAY}/admin/curated-items/${params.id}/decision?decision=${encodeURIComponent(decision)}`, {
    method: "POST", headers: adminApiHeaders(),
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
import { NextResponse } from "next/server";
import { requireSuperAdminApi } from "@/lib/admin/requireSuperAdminApi";
import { adminApiHeaders } from "@/lib/admin/adminApiHeaders";

export async function POST(
  req: Request,
  { params }: { params: { userId: string } }
) {
  const gate = await requireSuperAdminApi();
  if (gate instanceof NextResponse) return gate;

  const body = await req.json();
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || process.env.RAILWAY_API_URL || "https://culturix-trend-collector-production.up.railway.app";
  const res = await fetch(`${apiUrl}/admin/users/${params.userId}/plan`, {
    method: "POST",
    headers: adminApiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

import { NextResponse } from "next/server";
import { requireSuperAdminApi } from "@/lib/admin/requireSuperAdminApi";
import { adminApiHeaders } from "@/lib/admin/adminApiHeaders";

export async function POST() {
  const gate = await requireSuperAdminApi();
  if (gate instanceof NextResponse) return gate;

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || process.env.RAILWAY_API_URL || "https://culturix-trend-collector-production.up.railway.app";
  const res = await fetch(`${apiUrl}/admin/integration-health/check-now`, { method: "POST", headers: adminApiHeaders() });
  const body = await res.json().catch(() => ({}));
  return NextResponse.json(body, { status: res.status });
}

import { NextResponse } from "next/server";
import { requireSuperAdminApi } from "@/lib/admin/requireSuperAdminApi";
import { adminApiHeaders } from "@/lib/admin/adminApiHeaders";

export async function POST(
  _req: Request,
  { params }: { params: { userId: string; action: string } }
) {
  const gate = await requireSuperAdminApi();
  if (gate instanceof NextResponse) return gate;

  const { userId, action } = params;
  if (action !== "approve" && action !== "reject") {
    return NextResponse.json({ error: "Invalid action" }, { status: 400 });
  }

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || process.env.RAILWAY_API_URL || "https://culturix-trend-collector-production.up.railway.app";
  const res = await fetch(`${apiUrl}/admin/users/${userId}/${action}`, { method: "POST", headers: adminApiHeaders() });
  const body = await res.json().catch(() => ({}));
  return NextResponse.json(body, { status: res.status });
}

import { NextResponse } from "next/server";
import { requireSuperAdminApi } from "@/lib/admin/requireSuperAdminApi";
import { adminApiHeaders } from "@/lib/admin/adminApiHeaders";

export async function GET() {
  const gate = await requireSuperAdminApi();
  if (gate instanceof NextResponse) return gate;

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

  if (!apiUrl) {
    return NextResponse.json({ error: "NEXT_PUBLIC_API_URL is not set", apiUrl: null });
  }

  const endpoints = ["/health", "/admin/trends?limit=1", "/admin/clusters?limit=1"];
  const results: Record<string, unknown> = { apiUrl };

  for (const ep of endpoints) {
    try {
      const res = await fetch(`${apiUrl}${ep}`, {
        cache: "no-store",
        headers: adminApiHeaders(),
        signal: AbortSignal.timeout(8000),
      });
      results[ep] = { status: res.status, ok: res.ok };
    } catch (e) {
      results[ep] = { error: String(e) };
    }
  }

  return NextResponse.json(results);
}

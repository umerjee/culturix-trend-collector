import { NextResponse } from "next/server";

export async function GET() {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

  if (!apiUrl) {
    return NextResponse.json({ error: "NEXT_PUBLIC_API_URL is not set", apiUrl: null });
  }

  const endpoints = ["/health", "/admin/trends?limit=1", "/admin/clusters?limit=1"];
  const results: Record<string, unknown> = { apiUrl };

  for (const ep of endpoints) {
    try {
      const res = await fetch(`${apiUrl}${ep}`, { cache: "no-store", signal: AbortSignal.timeout(8000) });
      results[ep] = { status: res.status, ok: res.ok };
    } catch (e) {
      results[ep] = { error: String(e) };
    }
  }

  return NextResponse.json(results);
}

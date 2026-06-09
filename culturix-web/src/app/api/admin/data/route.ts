import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const SUPERADMIN_EMAIL = "umer.ali79@gmail.com";

export async function GET(req: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user || user.email !== SUPERADMIN_EMAIL) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  const { searchParams } = new URL(req.url);
  const type = searchParams.get("type");
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

  if (!apiUrl) {
    return NextResponse.json({ error: "NEXT_PUBLIC_API_URL not set" }, { status: 503 });
  }

  const pathMap: Record<string, string> = {
    trends:   "/admin/trends?limit=200",
    clusters: "/admin/clusters?limit=50",
    personas: "/admin/personas?limit=50",
    digests:  "/admin/digests?limit=20",
    users:    "/admin/users",
  };

  const path = type && pathMap[type];
  if (!path) {
    return NextResponse.json({ error: "Invalid type" }, { status: 400 });
  }

  try {
    const res = await fetch(`${apiUrl}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) {
      return NextResponse.json({ error: `Backend returned ${res.status}` }, { status: res.status });
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}

import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const SUPERADMIN_EMAIL = "umer.ali79@gmail.com";

export async function POST() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user || user.email !== SUPERADMIN_EMAIL) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || process.env.RAILWAY_API_URL || "https://culturix-trend-collector-production.up.railway.app";
  const res = await fetch(`${apiUrl}/admin/collect`, { method: "POST" });
  const body = await res.json().catch(() => ({}));
  return NextResponse.json(body, { status: res.status });
}

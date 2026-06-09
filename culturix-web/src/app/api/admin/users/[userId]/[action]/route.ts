import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const SUPERADMIN_EMAIL = "umer.ali79@gmail.com";

export async function POST(
  _req: Request,
  { params }: { params: { userId: string; action: string } }
) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user || user.email !== SUPERADMIN_EMAIL) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  const { userId, action } = params;
  if (action !== "approve" && action !== "reject") {
    return NextResponse.json({ error: "Invalid action" }, { status: 400 });
  }

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? process.env.RAILWAY_API_URL ?? "http://localhost:8000";
  const res = await fetch(`${apiUrl}/admin/users/${userId}/${action}`, { method: "POST" });
  const body = await res.json().catch(() => ({}));
  return NextResponse.json(body, { status: res.status });
}

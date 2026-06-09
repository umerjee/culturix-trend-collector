import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const SUPERADMIN_EMAIL = "umer.ali79@gmail.com";

export async function POST(
  req: Request,
  { params }: { params: { userId: string } }
) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user || user.email !== SUPERADMIN_EMAIL) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  const body = await req.json();
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? process.env.RAILWAY_API_URL ?? "http://localhost:8000";
  const res = await fetch(`${apiUrl}/admin/users/${params.userId}/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

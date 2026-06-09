import { createClient } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

export async function POST() {
  const supabase = createClient();
  await supabase.auth.signOut();
  return NextResponse.redirect(new URL("/signup", process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"));
}

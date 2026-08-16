import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { isSuperAdminEmail } from "./superadmin";

// For Route Handlers. Usage:
//   const gate = await requireSuperAdminApi();
//   if (gate instanceof NextResponse) return gate;
export async function requireSuperAdminApi(): Promise<NextResponse | { email: string }> {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!isSuperAdminEmail(user?.email)) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  return { email: user!.email! };
}

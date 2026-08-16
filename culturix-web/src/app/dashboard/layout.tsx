import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

// Hoists the shared auth guard + outer page shell previously copy-pasted in
// every dashboard/** page.tsx. Each page still fetches its own user (it
// needs user.id for personalized data) and renders its own <AppNav
// active=... product=... /> — those genuinely differ per page.
export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

  return <div className="min-h-screen bg-gray-50">{children}</div>;
}

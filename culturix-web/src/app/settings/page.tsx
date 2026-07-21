import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import AppNav from "@/components/AppNav";
import SettingsForm from "@/components/SettingsForm";

export const dynamic = "force-dynamic";

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

export default async function SettingsPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

  const isSuperAdmin = user.email === "umer.ali79@gmail.com";
  let plan: "free" | "pro" = isSuperAdmin ? "pro" : "free";
  if (!isSuperAdmin) {
    try {
      const approvalRes = await fetch(`${RAILWAY}/api/users/${user.id}/approved`, { cache: "no-store" });
      if (approvalRes.ok) {
        const info = await approvalRes.json();
        if (info.plan === "pro") plan = "pro";
      }
    } catch {
      // Railway unreachable — fall through with the free-plan default
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <AppNav active="settings" isSuperAdmin={isSuperAdmin} />
      <SettingsForm userId={user.id} initialPlan={plan} />
    </div>
  );
}

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { isSuperAdminEmail } from "@/lib/admin/superadmin";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import AppNav from "@/components/AppNav";
import SettingsForm from "@/components/SettingsForm";

export const dynamic = "force-dynamic";

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: { profile?: string };
}) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

  const isSuperAdmin = isSuperAdminEmail(user.email);
  let plan: "free" | "pro" = isSuperAdmin ? "pro" : "free";
  if (!isSuperAdmin) {
    try {
      const approvalRes = await fetch(`${RAILWAY_API_BASE}/api/users/${user.id}/approved`, { cache: "no-store" });
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
      <AppNav active="settings" isSuperAdmin={isSuperAdmin} product="posting-ideation" />
      <SettingsForm userId={user.id} initialPlan={plan} initialProfileId={searchParams.profile} />
    </div>
  );
}

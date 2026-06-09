import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import AdminDashboard from "@/components/AdminDashboard";

const SUPERADMIN_EMAIL = "umer.ali79@gmail.com";

export default async function AdminPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user || user.email !== SUPERADMIN_EMAIL) redirect("/dashboard");

  return <AdminDashboard />;
}

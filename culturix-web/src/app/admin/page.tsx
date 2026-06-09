import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import AdminDashboard from "@/components/AdminDashboard";

const SUPERADMIN_EMAIL = "umer.ali79@gmail.com";

export default async function AdminPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user || user.email !== SUPERADMIN_EMAIL) redirect("/dashboard");

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  const [trendsRes, clustersRes, personasRes, digestsRes, usersRes] = await Promise.allSettled([
    fetch(`${apiUrl}/trends/recent?limit=200`, { cache: "no-store" }),
    fetch(`${apiUrl}/clusters/recent?limit=50`, { cache: "no-store" }),
    fetch(`${apiUrl}/personas/recent?limit=50`, { cache: "no-store" }),
    fetch(`${apiUrl}/admin/digests?limit=20`, { cache: "no-store" }),
    fetch(`${apiUrl}/admin/users`, { cache: "no-store" }),
  ]);

  const trends   = trendsRes.status   === "fulfilled" && trendsRes.value.ok   ? await trendsRes.value.json()   : [];
  const clusters = clustersRes.status === "fulfilled" && clustersRes.value.ok ? await clustersRes.value.json() : [];
  const personas = personasRes.status === "fulfilled" && personasRes.value.ok ? await personasRes.value.json() : [];
  const digests  = digestsRes.status  === "fulfilled" && digestsRes.value.ok  ? await digestsRes.value.json()  : [];
  const users    = usersRes.status    === "fulfilled" && usersRes.value.ok    ? await usersRes.value.json()    : [];

  return <AdminDashboard trends={trends} clusters={clusters} personas={personas} digests={digests} users={users} apiUrl={apiUrl} />;
}

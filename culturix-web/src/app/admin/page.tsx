import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import AdminDashboard from "@/components/AdminDashboard";

const SUPERADMIN_EMAIL = "umer.ali79@gmail.com";

export default async function AdminPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user || user.email !== SUPERADMIN_EMAIL) redirect("/dashboard");

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
  const apiMissing = !apiUrl;
  const base = apiUrl || "http://localhost:8000";

  const [trendsRes, clustersRes, personasRes, digestsRes, usersRes] = await Promise.allSettled([
    fetch(`${base}/trends/recent?limit=200`, { cache: "no-store" }),
    fetch(`${base}/clusters/recent?limit=50`, { cache: "no-store" }),
    fetch(`${base}/personas/recent?limit=50`, { cache: "no-store" }),
    fetch(`${base}/admin/digests?limit=20`, { cache: "no-store" }),
    fetch(`${base}/admin/users`, { cache: "no-store" }),
  ]);

  const trends   = trendsRes.status   === "fulfilled" && trendsRes.value.ok   ? await trendsRes.value.json()   : [];
  const clusters = clustersRes.status === "fulfilled" && clustersRes.value.ok ? await clustersRes.value.json() : [];
  const personas = personasRes.status === "fulfilled" && personasRes.value.ok ? await personasRes.value.json() : [];
  const digests  = digestsRes.status  === "fulfilled" && digestsRes.value.ok  ? await digestsRes.value.json()  : [];
  const users    = usersRes.status    === "fulfilled" && usersRes.value.ok    ? await usersRes.value.json()    : [];

  if (apiMissing) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-8">
        <div className="bg-white border border-amber-200 rounded-2xl p-8 max-w-lg w-full shadow-sm">
          <h2 className="font-bold text-gray-900 text-lg mb-2">⚠️ Backend URL not configured</h2>
          <p className="text-sm text-gray-600 mb-4">
            The admin dashboard needs <code className="bg-gray-100 px-1 rounded">NEXT_PUBLIC_API_URL</code> set
            in your Vercel environment variables to reach the Railway backend.
          </p>
          <ol className="text-sm text-gray-600 space-y-2 list-decimal list-inside mb-6">
            <li>Open <strong>Railway</strong> → your project → click the <strong>web service</strong> (not the database)</li>
            <li>Go to <strong>Settings → Networking</strong> → copy the <strong>Public domain</strong> URL</li>
            <li>Open <strong>Vercel</strong> → your project → <strong>Settings → Environment Variables</strong></li>
            <li>Add: <code className="bg-gray-100 px-1 rounded">NEXT_PUBLIC_API_URL</code> = the Railway URL</li>
            <li>Click <strong>Save</strong>, then <strong>Deployments → Redeploy</strong></li>
          </ol>
          <a href="/dashboard" className="text-sm text-blue-600 hover:underline">← Back to dashboard</a>
        </div>
      </div>
    );
  }

  return <AdminDashboard trends={trends} clusters={clusters} personas={personas} digests={digests} users={users} apiUrl={base} />;
}

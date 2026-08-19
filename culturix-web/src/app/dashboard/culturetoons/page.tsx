import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { isSuperAdminEmail } from "@/lib/admin/superadmin";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import { internalApiHeaders } from "@/lib/internalApiHeaders";
import AppNav from "@/components/AppNav";
import CultureToonApp from "@/components/CultureToonApp";
import type { CharacterBrand } from "@/lib/types";

export default async function CultureToonsPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

  const isSuperAdmin = isSuperAdminEmail(user.email);

  let brands: CharacterBrand[] = [];
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/api/culturetoons/brands?user_id=${user.id}`, {
      cache: "no-store",
      headers: internalApiHeaders(),
    });
    if (res.ok) {
      const data = await res.json();
      brands = Array.isArray(data) ? data : [];
    }
  } catch {
    brands = [];
  }

  return (
    <>
      <AppNav active="culturetoons" isSuperAdmin={isSuperAdmin} product="culturetoons" />

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Character-Based Posting</h1>
          <p className="text-sm text-gray-500 mt-1">
            Cartoon characters riffing on cultural trends — build your character library, write skit
            scripts, and track production through to posting. Run several independent "toon accounts"
            (e.g. Funny Clips, Baby Videos) side by side, all managed here.
          </p>
        </div>

        <CultureToonApp initialBrands={brands} />
      </main>
    </>
  );
}

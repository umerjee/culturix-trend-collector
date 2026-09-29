import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import { internalApiHeaders } from "@/lib/internalApiHeaders";
import CultureToonApp from "@/components/CultureToonApp";
import type { CharacterBrand } from "@/lib/types";

export default async function AdminComedyVideosPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

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
    <div className="max-w-6xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Comedy studio</h1>
        <p className="mt-1 max-w-2xl text-sm text-gray-500">
          Create and manage toon brands, characters, scripts, and video production from the admin workspace.
        </p>
      </div>
      <CultureToonApp initialBrands={brands} initialTab="toons" showWorldLibrary />
    </div>
  );
}
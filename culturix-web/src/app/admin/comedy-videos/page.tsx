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
  let brandLoadError = "";
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/api/culturetoons/brands?user_id=${user.id}`, {
      cache: "no-store",
      headers: internalApiHeaders(),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!Array.isArray(data)) throw new Error("Invalid brand list response");
    brands = data;
  } catch {
    brandLoadError = "Could not load your CultureToons brands. Check your connection and retry.";
  }

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Comedy studio</h1>
        <p className="mt-1 max-w-2xl text-sm text-gray-500">
          Create and manage toon brands, characters, scripts, and video production from the admin workspace.
        </p>
      </div>
      {brandLoadError ? (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <span>{brandLoadError}</span>
          <a href="/admin/comedy-videos" className="font-semibold underline underline-offset-2">Retry</a>
        </div>
      ) : (
        <CultureToonApp initialBrands={brands} initialTab="toons" showWorldLibrary />
      )}
    </div>
  );
}
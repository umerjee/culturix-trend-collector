import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import AppNav from "@/components/AppNav";
import CultureToonBrandForm from "@/components/CultureToonBrandForm";
import CultureToonWorkspace from "@/components/CultureToonWorkspace";
import type { CharacterBrand, Character, CharacterVariant, ToonBackground, ToonScript, Toon } from "@/lib/types";

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

async function fetchJson<T>(path: string, userId: string, fallback: T): Promise<T> {
  try {
    const sep = path.includes("?") ? "&" : "?";
    const res = await fetch(`${RAILWAY}${path}${sep}user_id=${userId}`, { cache: "no-store" });
    if (!res.ok) return fallback;
    return await res.json();
  } catch {
    return fallback;
  }
}

export default async function CultureToonsPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

  const isSuperAdmin = user.email === "umer.ali79@gmail.com";
  const brand = await fetchJson<CharacterBrand | null>("/api/culturetoons/brand", user.id, null);

  const [characters, variants, backgrounds, scripts, toons] = brand
    ? await Promise.all([
        fetchJson<Character[]>("/api/culturetoons/characters?active_only=false", user.id, []),
        fetchJson<CharacterVariant[]>("/api/culturetoons/variants?active_only=false", user.id, []),
        fetchJson<ToonBackground[]>("/api/culturetoons/backgrounds?active_only=false", user.id, []),
        fetchJson<ToonScript[]>("/api/culturetoons/scripts", user.id, []),
        fetchJson<Toon[]>("/api/culturetoons/toons", user.id, []),
      ])
    : [[], [], [], [], []];

  return (
    <div className="min-h-screen bg-gray-50">
      <AppNav active="culturetoons" isSuperAdmin={isSuperAdmin} product="culturetoons" />

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Character-Based Posting</h1>
          <p className="text-sm text-gray-500 mt-1">
            Cartoon characters riffing on cultural trends — build your character library, write skit
            scripts, and track production through to posting.
          </p>
        </div>

        {brand ? (
          <CultureToonWorkspace
            brand={brand}
            initialCharacters={characters}
            initialVariants={variants}
            initialBackgrounds={backgrounds}
            initialScripts={scripts}
            initialToons={toons}
          />
        ) : (
          <CultureToonBrandForm />
        )}
      </main>
    </div>
  );
}

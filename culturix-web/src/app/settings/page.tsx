"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Zap, Loader2, Check } from "lucide-react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import PersonaChips from "@/components/PersonaChips";
import {
  PLATFORMS,
  REGIONS,
  CONTENT_GOALS,
  CONTENT_TONES,
  type UserProfile,
} from "@/lib/types";

function Chip({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
        selected
          ? "bg-blue-600 border-blue-600 text-white"
          : "bg-white border-gray-200 text-gray-600 hover:border-blue-300"
      }`}
    >
      {selected && <Check className="h-3 w-3" />}
      {label}
    </button>
  );
}

export default function SettingsPage() {
  const router = useRouter();
  const supabase = createClient();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [profile, setProfile] = useState<Partial<UserProfile>>({
    target_platforms: [],
    target_regions: [],
    content_goals: [],
    content_tones: [],
    persona_tags: [],
    industry_niche: "",
    delivery_freq: "daily",
    delivery_time: "07:00",
    target_age_min: 18,
    target_age_max: 35,
  });

  useEffect(() => {
    async function load() {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) { router.push("/signup"); return; }

      const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
      try {
        const res = await fetch(`${apiUrl}/api/users/profile?user_id=${user.id}`);
        if (res.ok) {
          const data = await res.json();
          setProfile(data);
        }
      } catch {}
      setLoading(false);
    }
    load();
  }, []);

  function toggle(field: keyof UserProfile, val: string) {
    const arr = (profile[field] as string[]) ?? [];
    setProfile((p) => ({
      ...p,
      [field]: arr.includes(val) ? arr.filter((v) => v !== val) : [...arr, val],
    }));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;

    await fetch("/api/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...profile, user_id: user.id }),
    });

    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  }

  async function handleSignOut() {
    await supabase.auth.signOut();
    router.push("/");
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-100">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-blue-600" />
            <span className="font-bold text-lg tracking-tight">Culturix</span>
          </Link>
          <button onClick={handleSignOut} className="text-sm text-gray-500 hover:text-gray-700">
            Sign out
          </button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-10">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
          <p className="text-sm text-gray-500 mt-1">Update your content profile and delivery preferences.</p>
        </div>

        <form onSubmit={handleSave} className="space-y-8">
          {/* Audience */}
          <section className="bg-white rounded-2xl border border-gray-100 p-6">
            <h2 className="font-semibold text-gray-900 mb-5">Audience</h2>
            <div className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  Age range: <span className="text-blue-600">{profile.target_age_min}–{profile.target_age_max}</span>
                </label>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-gray-400 mb-1">Min</p>
                    <input
                      type="range" min={13} max={65}
                      value={profile.target_age_min ?? 18}
                      onChange={(e) => setProfile((p) => ({ ...p, target_age_min: +e.target.value }))}
                      className="w-full accent-blue-600"
                    />
                  </div>
                  <div>
                    <p className="text-xs text-gray-400 mb-1">Max</p>
                    <input
                      type="range" min={13} max={65}
                      value={profile.target_age_max ?? 35}
                      onChange={(e) => setProfile((p) => ({ ...p, target_age_max: +e.target.value }))}
                      className="w-full accent-blue-600"
                    />
                  </div>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Platforms</label>
                <div className="flex flex-wrap gap-2">
                  {PLATFORMS.map((p) => (
                    <Chip key={p} label={p} selected={(profile.target_platforms ?? []).includes(p)} onClick={() => toggle("target_platforms", p)} />
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Regions</label>
                <div className="flex flex-wrap gap-2">
                  {REGIONS.map((r) => (
                    <Chip key={r} label={r} selected={(profile.target_regions ?? []).includes(r)} onClick={() => toggle("target_regions", r)} />
                  ))}
                </div>
              </div>
            </div>
          </section>

          {/* Goals & Tone */}
          <section className="bg-white rounded-2xl border border-gray-100 p-6">
            <h2 className="font-semibold text-gray-900 mb-5">Goals & Tone</h2>
            <div className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Content goals</label>
                <div className="flex flex-wrap gap-2">
                  {CONTENT_GOALS.map((g) => (
                    <Chip key={g} label={g} selected={(profile.content_goals ?? []).includes(g)} onClick={() => toggle("content_goals", g)} />
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Content tones</label>
                <div className="flex flex-wrap gap-2">
                  {CONTENT_TONES.map((t) => (
                    <Chip key={t} label={t} selected={(profile.content_tones ?? []).includes(t)} onClick={() => toggle("content_tones", t)} />
                  ))}
                </div>
              </div>
            </div>
          </section>

          {/* Industry & Personas */}
          <section className="bg-white rounded-2xl border border-gray-100 p-6">
            <h2 className="font-semibold text-gray-900 mb-5">Industry & Personas</h2>
            <div className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Industry niche</label>
                <input
                  type="text"
                  value={profile.industry_niche ?? ""}
                  onChange={(e) => setProfile((p) => ({ ...p, industry_niche: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-blue-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Persona tags</label>
                <PersonaChips
                  selected={profile.persona_tags ?? []}
                  onChange={(tags) => setProfile((p) => ({ ...p, persona_tags: tags }))}
                />
              </div>
            </div>
          </section>

          {/* Delivery */}
          <section className="bg-white rounded-2xl border border-gray-100 p-6">
            <h2 className="font-semibold text-gray-900 mb-5">Delivery</h2>
            <div className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-3">Frequency</label>
                <div className="flex gap-3">
                  {(["daily", "weekly"] as const).map((f) => (
                    <button
                      key={f}
                      type="button"
                      onClick={() => setProfile((p) => ({ ...p, delivery_freq: f }))}
                      className={`flex-1 rounded-xl border-2 py-3 text-sm font-semibold capitalize transition-all ${
                        profile.delivery_freq === f ? "border-blue-600 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-600"
                      }`}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Delivery time</label>
                <input
                  type="time"
                  value={profile.delivery_time ?? "07:00"}
                  onChange={(e) => setProfile((p) => ({ ...p, delivery_time: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-blue-500 outline-none"
                />
              </div>
            </div>
          </section>

          <button
            type="submit"
            disabled={saving}
            className="w-full bg-blue-600 text-white font-semibold py-3.5 rounded-xl hover:bg-blue-700 disabled:opacity-60 transition-colors flex items-center justify-center gap-2"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {saved ? "Saved!" : saving ? "Saving..." : "Save changes"}
          </button>
        </form>
      </main>
    </div>
  );
}

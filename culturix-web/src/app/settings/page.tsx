"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Zap, Loader2, Check, Plus, Trash2, ChevronRight } from "lucide-react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import PersonaChips from "@/components/PersonaChips";
import {
  PLATFORMS, REGIONS, CONTENT_GOALS, CONTENT_TONES,
  type ContentProfile,
} from "@/lib/types";

const EMPTY_PROFILE: Omit<ContentProfile, "id" | "user_id" | "created_at"> = {
  name: "",
  industry_niche: "",
  target_platforms: [],
  target_regions: [],
  content_goals: [],
  content_tones: [],
  persona_tags: [],
  target_age_min: 18,
  target_age_max: 35,
  delivery_freq: "daily",
  delivery_time: "07:00",
  is_active: true,
};

function Chip({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
        selected ? "bg-blue-600 border-blue-600 text-white" : "bg-white border-gray-200 text-gray-600 hover:border-blue-300"
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
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const [plan, setPlan] = useState<"free" | "pro">("free");

  const [profiles, setProfiles] = useState<ContentProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Omit<ContentProfile, "id" | "user_id" | "created_at">>(EMPTY_PROFILE);
  const [isNew, setIsNew] = useState(false);

  const selected = profiles.find(p => p.id === selectedId) ?? null;
  const profileLimit = plan === "pro" ? 10 : 1;
  const canAddMore = profiles.length < profileLimit;

  useEffect(() => {
    async function load() {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) { router.push("/signup"); return; }

      try {
        // Load content profiles
        const res = await fetch("/api/content-profiles");
        if (res.ok) {
          const data: ContentProfile[] = await res.json();
          setProfiles(data);
          if (data.length > 0) {
            setSelectedId(data[0].id);
            setDraft({ ...EMPTY_PROFILE, ...data[0] });
          }
        }

        // Load plan info — superadmin is always pro
        if (user.email === "umer.ali79@gmail.com") {
          setPlan("pro");
        } else {
          const apiUrl = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";
          const approvalRes = await fetch(`${apiUrl}/api/users/${user.id}/approved`, { cache: "no-store" });
          if (approvalRes.ok) {
            const info = await approvalRes.json();
            if (info.plan) setPlan(info.plan);
          }
        }
      } catch {}
      setLoading(false);
    }
    load();
  }, []);

  function selectProfile(p: ContentProfile) {
    setSelectedId(p.id);
    setDraft({ ...EMPTY_PROFILE, ...p });
    setIsNew(false);
    setSaved(false);
    setError("");
  }

  function startNew() {
    setSelectedId(null);
    setDraft({ ...EMPTY_PROFILE });
    setIsNew(true);
    setSaved(false);
    setError("");
  }

  function toggle(field: keyof typeof draft, val: string) {
    const arr = (draft[field] as string[]) ?? [];
    setDraft(d => ({
      ...d,
      [field]: arr.includes(val) ? arr.filter(v => v !== val) : [...arr, val],
    }));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.name.trim()) { setError("Profile name is required."); return; }
    setSaving(true);
    setError("");
    try {
      if (isNew) {
        const res = await fetch("/api/content-profiles", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        });
        if (!res.ok) {
          const err = await res.json();
          setError(err.detail ?? "Failed to create profile.");
          return;
        }
        const created: ContentProfile = await res.json();
        setProfiles(prev => [...prev, created]);
        setSelectedId(created.id);
        setIsNew(false);
      } else if (selectedId) {
        const res = await fetch(`/api/content-profiles/${selectedId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        });
        if (!res.ok) { setError("Failed to save."); return; }
        const updated: ContentProfile = await res.json();
        setProfiles(prev => prev.map(p => p.id === selectedId ? updated : p));
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!selectedId || profiles.length <= 1) return;
    if (!confirm("Delete this content profile?")) return;
    setDeleting(true);
    await fetch(`/api/content-profiles/${selectedId}`, { method: "DELETE" });
    const remaining = profiles.filter(p => p.id !== selectedId);
    setProfiles(remaining);
    if (remaining.length > 0) selectProfile(remaining[0]);
    setDeleting(false);
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
      <header className="bg-white border-b border-gray-100 sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-blue-600" />
            <span className="font-bold text-lg tracking-tight">Culturix</span>
          </Link>
          <div className="flex items-center gap-4">
            <span className={`text-xs font-semibold px-2 py-1 rounded-full ${plan === "pro" ? "bg-indigo-100 text-indigo-700" : "bg-gray-100 text-gray-500"}`}>
              {plan === "pro" ? "Pro" : "Free"}
            </span>
            <button onClick={handleSignOut} className="text-sm text-gray-500 hover:text-gray-700">
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-10 space-y-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
          <p className="text-sm text-gray-500 mt-1">Manage your content profiles and delivery preferences.</p>
        </div>

        {/* Profile selector */}
        <section className="bg-white rounded-2xl border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="font-semibold text-gray-900">Content profiles</h2>
              <p className="text-xs text-gray-400 mt-0.5">
                {plan === "free"
                  ? `Free plan: 1 profile. Upgrade to Pro for up to 10.`
                  : `Pro plan: ${profiles.length} / 10 profiles.`}
              </p>
            </div>
            <button
              onClick={startNew}
              disabled={!canAddMore}
              title={!canAddMore ? `Upgrade to Pro to add more profiles` : ""}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              <Plus className="h-3.5 w-3.5" /> New profile
            </button>
          </div>

          {profiles.length === 0 && !isNew && (
            <p className="text-sm text-gray-400 text-center py-4">No profiles yet. Create your first one.</p>
          )}

          <div className="space-y-1">
            {profiles.map(p => (
              <button
                key={p.id}
                onClick={() => selectProfile(p)}
                className={`w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm transition-colors text-left ${
                  selectedId === p.id && !isNew ? "bg-blue-50 text-blue-700 font-medium" : "hover:bg-gray-50 text-gray-700"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`h-2 w-2 rounded-full ${p.is_active ? "bg-green-400" : "bg-gray-300"}`} />
                  <span>{p.name || "Untitled"}</span>
                  {p.industry_niche && <span className="text-xs text-gray-400">· {p.industry_niche}</span>}
                </div>
                <ChevronRight className="h-4 w-4 text-gray-300" />
              </button>
            ))}
            {isNew && (
              <div className="px-4 py-3 rounded-xl bg-blue-50 text-blue-700 text-sm font-medium flex items-center gap-3">
                <div className="h-2 w-2 rounded-full bg-blue-400" />
                New profile
              </div>
            )}
          </div>
        </section>

        {/* Edit form */}
        {(selected || isNew) && (
          <form onSubmit={handleSave} className="space-y-6">
            {/* Profile name */}
            <section className="bg-white rounded-2xl border border-gray-100 p-6">
              <h2 className="font-semibold text-gray-900 mb-4">Profile name</h2>
              <input
                type="text"
                value={draft.name}
                onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
                placeholder="e.g. Streetwear brand, Gaming channel…"
                className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-blue-500 outline-none"
              />
            </section>

            {/* Industry & Personas */}
            <section className="bg-white rounded-2xl border border-gray-100 p-6">
              <h2 className="font-semibold text-gray-900 mb-5">Industry & Personas</h2>
              <div className="space-y-5">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Industry niche</label>
                  <input
                    type="text"
                    value={draft.industry_niche ?? ""}
                    onChange={e => setDraft(d => ({ ...d, industry_niche: e.target.value }))}
                    placeholder="e.g. Streetwear, SaaS, Beauty…"
                    className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-blue-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Persona tags</label>
                  <PersonaChips
                    selected={draft.persona_tags ?? []}
                    onChange={tags => setDraft(d => ({ ...d, persona_tags: tags }))}
                  />
                </div>
              </div>
            </section>

            {/* Audience */}
            <section className="bg-white rounded-2xl border border-gray-100 p-6">
              <h2 className="font-semibold text-gray-900 mb-5">Audience</h2>
              <div className="space-y-5">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-3">
                    Age range: <span className="text-blue-600">{draft.target_age_min}–{draft.target_age_max}</span>
                  </label>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-xs text-gray-400 mb-1">Min</p>
                      <input type="range" min={13} max={65} value={draft.target_age_min}
                        onChange={e => setDraft(d => ({ ...d, target_age_min: +e.target.value }))}
                        className="w-full accent-blue-600" />
                    </div>
                    <div>
                      <p className="text-xs text-gray-400 mb-1">Max</p>
                      <input type="range" min={13} max={65} value={draft.target_age_max}
                        onChange={e => setDraft(d => ({ ...d, target_age_max: +e.target.value }))}
                        className="w-full accent-blue-600" />
                    </div>
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Platforms</label>
                  <div className="flex flex-wrap gap-2">
                    {PLATFORMS.map(p => (
                      <Chip key={p} label={p} selected={(draft.target_platforms ?? []).includes(p)} onClick={() => toggle("target_platforms", p)} />
                    ))}
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Regions</label>
                  <div className="flex flex-wrap gap-2">
                    {REGIONS.map(r => (
                      <Chip key={r} label={r} selected={(draft.target_regions ?? []).includes(r)} onClick={() => toggle("target_regions", r)} />
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
                    {CONTENT_GOALS.map(g => (
                      <Chip key={g} label={g} selected={(draft.content_goals ?? []).includes(g)} onClick={() => toggle("content_goals", g)} />
                    ))}
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Content tones</label>
                  <div className="flex flex-wrap gap-2">
                    {CONTENT_TONES.map(t => (
                      <Chip key={t} label={t} selected={(draft.content_tones ?? []).includes(t)} onClick={() => toggle("content_tones", t)} />
                    ))}
                  </div>
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
                    {(["daily", "weekly"] as const).map(f => (
                      <button key={f} type="button"
                        onClick={() => setDraft(d => ({ ...d, delivery_freq: f }))}
                        className={`flex-1 rounded-xl border-2 py-3 text-sm font-semibold capitalize transition-all ${
                          draft.delivery_freq === f ? "border-blue-600 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-600"
                        }`}
                      >{f}</button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Delivery time</label>
                  <input type="time" value={draft.delivery_time ?? "07:00"}
                    onChange={e => setDraft(d => ({ ...d, delivery_time: e.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-blue-500 outline-none" />
                </div>
              </div>
            </section>

            {error && <p className="text-sm text-red-600 bg-red-50 rounded-xl px-4 py-3">{error}</p>}

            <div className="flex gap-3">
              <button type="submit" disabled={saving}
                className="flex-1 bg-blue-600 text-white font-semibold py-3.5 rounded-xl hover:bg-blue-700 disabled:opacity-60 transition-colors flex items-center justify-center gap-2"
              >
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                {saved ? "Saved!" : saving ? "Saving…" : isNew ? "Create profile" : "Save changes"}
              </button>

              {!isNew && profiles.length > 1 && (
                <button type="button" onClick={handleDelete} disabled={deleting}
                  className="px-4 py-3.5 border border-red-200 text-red-500 rounded-xl hover:bg-red-50 disabled:opacity-50 transition"
                >
                  {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                </button>
              )}
            </div>
          </form>
        )}
      </main>
    </div>
  );
}

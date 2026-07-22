"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2, Check, Plus, Trash2, ChevronRight, CreditCard, Link2, Unlink, Sparkles, Copy } from "lucide-react";
import PersonaChips from "@/components/PersonaChips";
import {
  PLATFORMS, REGIONS, CONTENT_GOALS, CONTENT_TONES, CONTENT_FORMATS, AVATAR_TYPES, DELIVERY_DAYS,
  type ContentProfile, type AvatarTypePreset, type ConnectedAccount, type AccountSuggestions,
} from "@/lib/types";

const ALL_FORMAT_KEYS = CONTENT_FORMATS.map((f) => f.key);

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

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
  delivery_day_of_week: 0,
  is_active: true,
  publish_mode: "manual",
  preferred_formats: ALL_FORMAT_KEYS,
};

const SUPPORTED_SOCIAL_PLATFORMS: { key: ConnectedAccount["platform"]; label: string; live: boolean }[] = [
  { key: "youtube", label: "YouTube", live: true },
  { key: "tiktok", label: "TikTok", live: true },
  { key: "instagram", label: "Instagram", live: true },
  { key: "twitter", label: "X / Twitter", live: true },
];

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

interface Props {
  userId: string;
  initialPlan: "free" | "pro";
}

export default function SettingsForm({ userId, initialPlan }: Props) {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
      </div>
    }>
      <SettingsFormInner userId={userId} initialPlan={initialPlan} />
    </Suspense>
  );
}

function SettingsFormInner({ userId, initialPlan }: Props) {
  const searchParams = useSearchParams();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const [plan, setPlan] = useState<"free" | "pro">(initialPlan);
  const [billingLoading, setBillingLoading] = useState(false);
  const checkoutBanner = searchParams.get("checkout"); // "success" | "cancelled" | null
  const socialError = searchParams.get("social_error");
  const connectedParam = searchParams.get("connected");

  const [connectedAccounts, setConnectedAccounts] = useState<ConnectedAccount[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(true);

  const [suggestions, setSuggestions] = useState<AccountSuggestions | null>(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);
  const [copiedName, setCopiedName] = useState<string | null>(null);

  async function fetchSuggestions(profileId: string) {
    setSuggestionsLoading(true);
    setSuggestionsError(null);
    try {
      const res = await fetch(`/api/content-profiles/${profileId}/account-suggestions`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setSuggestionsError(data.detail ?? "Could not generate suggestions — try again.");
        return;
      }
      setSuggestions(data as AccountSuggestions);
    } catch {
      setSuggestionsError("Network error — could not generate suggestions.");
    } finally {
      setSuggestionsLoading(false);
    }
  }

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text).catch(() => {});
    setCopiedName(text);
    setTimeout(() => setCopiedName(null), 2000);
  }

  async function handleUpgrade() {
    setBillingLoading(true);
    try {
      const res = await fetch("/api/billing/checkout", { method: "POST" });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        setError(data.detail ?? data.error ?? "Could not start checkout.");
        setBillingLoading(false);
      }
    } catch {
      setError("Network error — could not start checkout.");
      setBillingLoading(false);
    }
  }

  async function handleManageBilling() {
    setBillingLoading(true);
    try {
      const res = await fetch("/api/billing/portal", { method: "POST" });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        setError(data.detail ?? data.error ?? "Could not open billing portal.");
        setBillingLoading(false);
      }
    } catch {
      setError("Network error — could not open billing portal.");
      setBillingLoading(false);
    }
  }

  const [profiles, setProfiles] = useState<ContentProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Omit<ContentProfile, "id" | "user_id" | "created_at">>(EMPTY_PROFILE);
  const [isNew, setIsNew] = useState(false);
  const [showAvatarGallery, setShowAvatarGallery] = useState(false);

  const selected = profiles.find(p => p.id === selectedId) ?? null;
  const profileLimit = plan === "pro" ? 10 : 1;
  const canAddMore = profiles.length < profileLimit;
  // Profile-scoped — reflects whether THIS niche has its own dedicated
  // account, not whether the user has a connection anywhere.
  const hasActiveConnection = connectedAccounts.some(a => a.status === "active" && a.content_profile_id === selectedId);

  async function loadConnectedAccounts() {
    setAccountsLoading(true);
    try {
      const res = await fetch(`${RAILWAY}/api/social/accounts?user_id=${userId}`, { cache: "no-store" });
      if (res.ok) setConnectedAccounts(await res.json());
    } catch {}
    setAccountsLoading(false);
  }

  async function handleDisconnect(platform: string, contentProfileId: string | null) {
    const qs = contentProfileId ? `&content_profile_id=${contentProfileId}` : "";
    await fetch(`${RAILWAY}/api/social/${platform}/disconnect?user_id=${userId}${qs}`, { method: "DELETE" });
    loadConnectedAccounts();
  }

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/content-profiles");
        if (res.ok) {
          const data: ContentProfile[] = await res.json();
          setProfiles(data);
          if (data.length > 0) {
            setSelectedId(data[0].id);
            setDraft({ ...EMPTY_PROFILE, ...data[0] });
          }
        }

        // Re-check plan client-side too — picks up a just-completed Stripe
        // checkout redirect before the webhook-driven server value would.
        if (userId) {
          const approvalRes = await fetch(`${RAILWAY}/api/users/${userId}/approved`, { cache: "no-store" });
          if (approvalRes.ok) {
            const info = await approvalRes.json();
            if (info.plan) setPlan(info.plan);
          }
        }
      } catch {}
      setLoading(false);
    }
    load();
    loadConnectedAccounts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectProfile(p: ContentProfile) {
    setSelectedId(p.id);
    setDraft({ ...EMPTY_PROFILE, ...p });
    setIsNew(false);
    setShowAvatarGallery(false);
    setSaved(false);
    setError("");
    setSuggestions(null);
    setSuggestionsError(null);
  }

  function startNew() {
    setSelectedId(null);
    setIsNew(false);
    setShowAvatarGallery(true);
    setSaved(false);
    setError("");
  }

  function startFromPreset(preset: AvatarTypePreset | null) {
    setSelectedId(null);
    setDraft({
      ...EMPTY_PROFILE,
      ...(preset && {
        name: preset.label,
        industry_niche: preset.industry_niche,
        target_platforms: preset.target_platforms,
        target_regions: preset.target_regions,
        content_goals: preset.content_goals,
        content_tones: preset.content_tones,
        persona_tags: preset.persona_tags,
      }),
    });
    setIsNew(true);
    setShowAvatarGallery(false);
    setSaved(false);
    setError("");
  }

  async function toggleActive(p: ContentProfile, e: React.MouseEvent) {
    e.stopPropagation();
    const res = await fetch(`/api/content-profiles/${p.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !p.is_active }),
    });
    if (res.ok) {
      const updated: ContentProfile = await res.json();
      setProfiles(prev => prev.map(x => x.id === p.id ? updated : x));
      if (selectedId === p.id) setDraft(d => ({ ...d, is_active: updated.is_active }));
    }
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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
      </div>
    );
  }

  return (
    <main className="max-w-3xl mx-auto px-4 sm:px-6 py-10 space-y-8">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
          <p className="text-sm text-gray-500 mt-1">Manage your content profiles and delivery preferences.</p>
        </div>
        <span className={`text-xs font-semibold px-2 py-1 rounded-full ${plan === "pro" ? "bg-indigo-100 text-indigo-700" : "bg-gray-100 text-gray-500"}`}>
          {plan === "pro" ? "Pro" : "Free"}
        </span>
      </div>

      {plan === "free" ? (
        <button
          onClick={handleUpgrade}
          disabled={billingLoading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white text-xs font-semibold rounded-lg hover:bg-indigo-700 disabled:opacity-60 transition"
        >
          {billingLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CreditCard className="h-3.5 w-3.5" />}
          Upgrade to Pro
        </button>
      ) : (
        <button
          onClick={handleManageBilling}
          disabled={billingLoading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-gray-200 text-gray-600 text-xs font-medium rounded-lg hover:border-gray-300 disabled:opacity-60 transition"
        >
          {billingLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CreditCard className="h-3.5 w-3.5" />}
          Manage billing
        </button>
      )}

      {checkoutBanner === "success" && (
        <p className="text-sm text-green-700 bg-green-50 border border-green-100 rounded-xl px-4 py-3">
          Payment successful — welcome to Pro! It may take a few seconds for your plan to update above.
        </p>
      )}
      {checkoutBanner === "cancelled" && (
        <p className="text-sm text-gray-500 bg-gray-50 border border-gray-100 rounded-xl px-4 py-3">
          Checkout cancelled — no charge was made.
        </p>
      )}
      {connectedParam && (
        <p className="text-sm text-green-700 bg-green-50 border border-green-100 rounded-xl px-4 py-3 capitalize">
          {connectedParam} connected successfully.
        </p>
      )}
      {socialError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
          Couldn&apos;t connect that account — please try again.
        </p>
      )}

      {/* Profile selector */}
      <section className="bg-white rounded-2xl border border-gray-100 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-semibold text-gray-900">Trend profiles</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Each profile tracks trends and generates content for one specific audience, niche, or region — add another to follow a different audience.{" "}
              {plan === "free"
                ? `Free plan: 1 profile. Upgrade to Pro for up to 10.`
                : `Pro plan: ${profiles.length} / 10 profiles.`}
            </p>
          </div>
          <button
            onClick={startNew}
            disabled={!canAddMore}
            title={!canAddMore ? `Upgrade to Pro to add more profiles` : ""}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition whitespace-nowrap"
          >
            <Plus className="h-3.5 w-3.5" /> Track new trend
          </button>
        </div>

        {profiles.length === 0 && !isNew && (
          <p className="text-sm text-gray-400 text-center py-4">No profiles yet. Create your first one.</p>
        )}

        <div className="grid sm:grid-cols-2 gap-3">
          {profiles.map(p => {
            const boundAccount = connectedAccounts.find(
              a => a.status === "active" && a.content_profile_id === p.id
            );
            const isSelected = selectedId === p.id && !isNew && !showAvatarGallery;
            const platforms = p.target_platforms ?? [];
            return (
              <div
                key={p.id}
                role="button"
                tabIndex={0}
                onClick={() => selectProfile(p)}
                onKeyDown={(e) => { if (e.key === "Enter") selectProfile(p); }}
                className={`text-left rounded-xl border p-4 space-y-3 cursor-pointer transition-colors ${
                  isSelected ? "border-blue-300 ring-1 ring-blue-100 bg-blue-50/30" : "border-gray-100 hover:border-gray-200"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className={`h-2 w-2 rounded-full shrink-0 ${p.is_active ? "bg-green-400" : "bg-gray-300"}`} />
                    <div className="min-w-0">
                      <p className="font-semibold text-sm text-gray-900 truncate">{p.name || "Untitled"}</p>
                      {p.industry_niche && <p className="text-xs text-gray-400 truncate">{p.industry_niche}</p>}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      onClick={(e) => toggleActive(p, e)}
                      title={p.is_active ? "Pause posting for this avatar" : "Activate posting for this avatar"}
                      className={`text-xs font-medium px-2.5 py-1 rounded-full transition-colors ${
                        p.is_active ? "bg-green-50 text-green-600 hover:bg-green-100" : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                      }`}
                    >
                      {p.is_active ? "Active" : "Paused"}
                    </button>
                    <ChevronRight className="h-4 w-4 text-gray-300" />
                  </div>
                </div>

                {platforms.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {platforms.slice(0, 4).map(pl => (
                      <span key={pl} className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-xs">{pl}</span>
                    ))}
                    {platforms.length > 4 && (
                      <span className="px-1.5 py-0.5 text-gray-400 text-xs">+{platforms.length - 4} more</span>
                    )}
                  </div>
                )}

                <div className="flex items-center gap-1.5 flex-wrap">
                  {boundAccount ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                      <Link2 className="h-3 w-3" /> @{boundAccount.platform_username ?? boundAccount.platform}
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700">
                      No dedicated account yet
                    </span>
                  )}
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-600 capitalize">
                    {p.publish_mode ?? "manual"}
                  </span>
                </div>
              </div>
            );
          })}
          {showAvatarGallery && (
            <div className="rounded-xl bg-blue-50 text-blue-700 text-sm font-medium flex items-center gap-3 p-4">
              <div className="h-2 w-2 rounded-full bg-blue-400" />
              Choosing avatar type…
            </div>
          )}
          {isNew && (
            <div className="rounded-xl bg-blue-50 text-blue-700 text-sm font-medium flex items-center gap-3 p-4">
              <div className="h-2 w-2 rounded-full bg-blue-400" />
              New profile
            </div>
          )}
        </div>
      </section>

      {/* Avatar type gallery */}
      {showAvatarGallery && (
        <section className="bg-white rounded-2xl border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="font-semibold text-gray-900">Choose an avatar type</h2>
              <p className="text-xs text-gray-400 mt-0.5">Pre-fills a starting point based on durable, evergreen audiences — fully editable after.</p>
            </div>
            <button type="button" onClick={() => setShowAvatarGallery(false)} className="text-xs text-gray-400 hover:text-gray-600 shrink-0">
              Cancel
            </button>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            {AVATAR_TYPES.map(preset => (
              <button
                key={preset.key}
                type="button"
                onClick={() => startFromPreset(preset)}
                className="text-left rounded-xl border border-gray-200 p-4 hover:border-blue-300 hover:bg-blue-50/50 transition-colors"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-lg">{preset.emoji}</span>
                  <span className="font-semibold text-sm text-gray-900">{preset.label}</span>
                </div>
                <p className="text-xs text-gray-500">{preset.description}</p>
              </button>
            ))}
            <button
              type="button"
              onClick={() => startFromPreset(null)}
              className="text-left rounded-xl border border-dashed border-gray-300 p-4 hover:border-blue-300 hover:bg-blue-50/50 transition-colors flex flex-col items-center justify-center gap-1 text-gray-400 hover:text-blue-600"
            >
              <Plus className="h-5 w-5" />
              <span className="text-xs font-medium">Start from scratch</span>
            </button>
          </div>
        </section>
      )}

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

          {/* Content format */}
          <section className="bg-white rounded-2xl border border-gray-100 p-6">
            <h2 className="font-semibold text-gray-900 mb-1">Content format</h2>
            <p className="text-xs text-gray-400 mb-4">
              What kind of content do you make? Ideas and generation tools focus on these.
            </p>
            <div className="grid gap-2">
              {CONTENT_FORMATS.map((f) => {
                const selected = (draft.preferred_formats ?? ALL_FORMAT_KEYS).includes(f.key);
                return (
                  <button
                    key={f.key}
                    type="button"
                    onClick={() => {
                      const current = draft.preferred_formats ?? ALL_FORMAT_KEYS;
                      const next = current.includes(f.key)
                        ? current.filter((k) => k !== f.key)
                        : [...current, f.key];
                      setDraft((d) => ({ ...d, preferred_formats: next }));
                    }}
                    className={`text-left rounded-xl border-2 p-3 transition-all ${
                      selected ? "border-blue-600 bg-blue-50" : "border-gray-200 hover:border-blue-200"
                    }`}
                  >
                    <p className={`text-sm font-semibold ${selected ? "text-blue-700" : "text-gray-700"}`}>
                      {selected && <Check className="h-3.5 w-3.5 inline mr-1.5" />}
                      {f.label}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">{f.description}</p>
                  </button>
                );
              })}
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
              {draft.delivery_freq === "weekly" && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-3">Day of week</label>
                  <div className="grid grid-cols-7 gap-1.5">
                    {DELIVERY_DAYS.map((day, i) => (
                      <button key={day} type="button"
                        onClick={() => setDraft(d => ({ ...d, delivery_day_of_week: i }))}
                        title={day}
                        className={`rounded-lg border-2 py-2 text-xs font-semibold transition-all ${
                          (draft.delivery_day_of_week ?? 0) === i ? "border-blue-600 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-600"
                        }`}
                      >{day.slice(0, 3)}</button>
                    ))}
                  </div>
                </div>
              )}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Delivery time</label>
                <input type="time" value={draft.delivery_time ?? "07:00"}
                  onChange={e => setDraft(d => ({ ...d, delivery_time: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-blue-500 outline-none" />
              </div>
            </div>
          </section>

          {/* This avatar's account — one dedicated connected account per profile/niche */}
          {isNew ? (
            <section className="bg-white rounded-2xl border border-gray-100 p-6">
              <h2 className="font-semibold text-gray-900 mb-1">This avatar&apos;s account</h2>
              <p className="text-xs text-gray-400">
                Save this profile first, then come back here to connect its dedicated account.
              </p>
            </section>
          ) : selectedId && (
            <section className="bg-white rounded-2xl border border-gray-100 p-6">
              <h2 className="font-semibold text-gray-900 mb-1">This avatar&apos;s account</h2>
              <p className="text-xs text-gray-400 mb-4">
                Connect the dedicated account you run for this niche so Culturix can publish to it and track
                performance — a different profile can have its own separate account.
              </p>

              {!connectedAccounts.some(a => a.status === "active" && a.content_profile_id === selectedId) && (
                <div className="mb-4">
                  <button
                    type="button"
                    onClick={() => fetchSuggestions(selectedId)}
                    disabled={suggestionsLoading}
                    className="w-full flex items-center justify-center gap-1.5 rounded-lg border border-gray-200 py-2 text-xs font-medium text-gray-500 hover:border-blue-300 hover:text-blue-600 transition-colors disabled:opacity-60"
                  >
                    {suggestionsLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                    {suggestionsLoading ? "Thinking…" : suggestions ? "Regenerate suggestions" : "Get name & platform suggestions"}
                  </button>
                  {suggestionsError && (
                    <p className="text-xs text-red-500 mt-2">{suggestionsError}</p>
                  )}
                  {suggestions && (
                    <div className="mt-3 space-y-3 rounded-xl bg-gray-50 border border-gray-100 p-4">
                      <div>
                        <p className="text-xs font-semibold text-gray-700 mb-1.5">Best platform fit</p>
                        <div className="space-y-1">
                          {suggestions.recommended_platforms.map((rp) => (
                            <p key={rp.platform} className="text-xs text-gray-600">
                              <span className="font-medium text-gray-900">{rp.platform}</span> — {rp.reason}
                            </p>
                          ))}
                        </div>
                      </div>
                      <div>
                        <p className="text-xs font-semibold text-gray-700 mb-1.5">Account name ideas</p>
                        <div className="space-y-1">
                          {suggestions.name_suggestions.map((ns) => (
                            <div key={ns.name} className="flex items-start justify-between gap-2 rounded-lg bg-white border border-gray-100 px-3 py-2">
                              <div className="min-w-0">
                                <p className="text-xs font-semibold text-gray-900 truncate">{ns.name}</p>
                                <p className="text-xs text-gray-400">{ns.reason}</p>
                              </div>
                              <button
                                type="button"
                                onClick={() => copyToClipboard(ns.name)}
                                title="Copy"
                                className="shrink-0 p-1 rounded text-gray-300 hover:text-gray-500 hover:bg-gray-100 transition-colors"
                              >
                                {copiedName === ns.name ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <p className="text-xs font-semibold text-gray-700 mb-1.5">Sample bio</p>
                        <div className="flex items-start justify-between gap-2 rounded-lg bg-white border border-gray-100 px-3 py-2">
                          <p className="text-xs text-gray-600">{suggestions.bio_suggestion}</p>
                          <button
                            type="button"
                            onClick={() => copyToClipboard(suggestions.bio_suggestion)}
                            title="Copy"
                            className="shrink-0 p-1 rounded text-gray-300 hover:text-gray-500 hover:bg-gray-100 transition-colors"
                          >
                            {copiedName === suggestions.bio_suggestion ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="space-y-2">
                {SUPPORTED_SOCIAL_PLATFORMS.map(({ key, label, live }) => {
                  const bound = connectedAccounts.find(
                    a => a.platform === key && a.status === "active" && a.content_profile_id === selectedId
                  );
                  const legacy = connectedAccounts.find(
                    a => a.platform === key && a.status === "active" && a.content_profile_id === null
                  );
                  if (!live) {
                    return (
                      <div key={key} className="flex items-center justify-between rounded-xl border border-gray-100 px-4 py-3 opacity-50">
                        <span className="text-sm font-medium text-gray-500">{label}</span>
                        <span className="text-xs text-gray-400">Coming soon</span>
                      </div>
                    );
                  }
                  return (
                    <div key={key} className="rounded-xl border border-gray-100 px-4 py-3">
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="text-sm font-medium text-gray-900">{label}</span>
                          {bound?.platform_username && (
                            <span className="text-xs text-gray-400 ml-2">@{bound.platform_username}</span>
                          )}
                        </div>
                        {accountsLoading ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-300" />
                        ) : bound ? (
                          <button
                            onClick={() => handleDisconnect(key, selectedId)}
                            className="inline-flex items-center gap-1.5 text-xs font-medium text-red-500 hover:text-red-600"
                          >
                            <Unlink className="h-3.5 w-3.5" /> Disconnect
                          </button>
                        ) : (
                          <a
                            href={`${RAILWAY}/api/social/${key}/connect?user_id=${userId}&content_profile_id=${selectedId}`}
                            className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:text-blue-700"
                          >
                            <Link2 className="h-3.5 w-3.5" /> Connect a dedicated account
                          </a>
                        )}
                      </div>
                      {!bound && legacy && (
                        <p className="text-xs text-amber-600 mt-2">
                          Currently shared with other profiles via @{legacy.platform_username ?? "an older connection"} —
                          not dedicated to this one. Connect a separate account above to give this niche its own.
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Publish mode */}
          <section className="bg-white rounded-2xl border border-gray-100 p-6">
            <h2 className="font-semibold text-gray-900 mb-1">Publish mode</h2>
            <p className="text-xs text-gray-400 mb-4">
              How ideas from this profile turn into real posts.
              {!hasActiveConnection && " Connect an account above to unlock Review and Auto."}
            </p>
            <div className="grid grid-cols-3 gap-3">
              {([
                { key: "manual", label: "Manual", desc: "You post it yourself, then paste the link to track it." },
                { key: "review", label: "Review", desc: "Click Publish on an idea — Culturix posts it for you." },
                { key: "auto", label: "Auto", desc: "Culturix publishes the best idea on its own, once a day." },
              ] as const).map(({ key, label, desc }) => {
                const disabled = key !== "manual" && !hasActiveConnection;
                return (
                  <button key={key} type="button" disabled={disabled}
                    onClick={() => setDraft(d => ({ ...d, publish_mode: key }))}
                    title={disabled ? "Connect an account first" : ""}
                    className={`text-left rounded-xl border-2 p-3 transition-all ${
                      draft.publish_mode === key ? "border-blue-600 bg-blue-50" : "border-gray-200"
                    } ${disabled ? "opacity-40 cursor-not-allowed" : "hover:border-blue-300"}`}
                  >
                    <p className={`text-sm font-semibold ${draft.publish_mode === key ? "text-blue-700" : "text-gray-700"}`}>{label}</p>
                    <p className="text-xs text-gray-400 mt-1">{desc}</p>
                  </button>
                );
              })}
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
  );
}

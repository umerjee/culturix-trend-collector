"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, Check, Plus } from "lucide-react";
import {
  PLATFORMS,
  IDEAS_ONLY_PLATFORMS,
  CONTENT_GOALS,
  CONTENT_TONES,
  CONTENT_FORMATS,
  AVATAR_TYPES,
  type AvatarTypePreset,
  type ContentProfile,
} from "@/lib/types";
import PersonaChips from "@/components/PersonaChips";
import RegionChips from "@/components/RegionChips";

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
          : "bg-white border-gray-200 text-gray-600 hover:border-blue-300 hover:text-blue-600"
      }`}
    >
      {selected && <Check className="h-3 w-3" />}
      {label}
    </button>
  );
}

function ToneCard({
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
      className={`rounded-xl border-2 p-4 text-sm font-medium text-left transition-all ${
        selected
          ? "border-blue-600 bg-blue-50 text-blue-700"
          : "border-gray-200 bg-white text-gray-600 hover:border-blue-200"
      }`}
    >
      {label}
    </button>
  );
}

// ── Zod schemas per step ──────────────────────────────────────────────────────

const step1Schema = z.object({
  targetAgeMin: z.number().min(13).max(65),
  targetAgeMax: z.number().min(13).max(65),
  targetPlatforms: z.array(z.string()).min(1, "Select at least one platform"),
  targetRegions: z.array(z.string()).min(1, "Select at least one region"),
});

type Step1 = z.infer<typeof step1Schema>;

interface Props {
  userId: string;
}

const ALL_FORMAT_KEYS = CONTENT_FORMATS.map((f) => f.key);

export default function OnboardingWizard({ userId: _userId }: Props) {
  const router = useRouter();
  // 0 = avatar gallery (pre-step, not counted in the progress bar), 1-5 = the
  // numbered wizard steps below.
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const [selectedPreset, setSelectedPreset] = useState<AvatarTypePreset | null>(null);
  const [profileName, setProfileName] = useState("");

  // Step 1 form
  const s1 = useForm<Step1>({
    resolver: zodResolver(step1Schema),
    defaultValues: {
      targetAgeMin: 18,
      targetAgeMax: 35,
      targetPlatforms: [],
      targetRegions: [],
    },
  });

  // Step 2 — preferred content formats (defaults to all three = unrestricted)
  const [preferredFormats, setPreferredFormats] = useState<string[]>(ALL_FORMAT_KEYS);

  // Step 3 — Goals & Tone
  const [goals, setGoals] = useState<string[]>([]);
  const [tones, setTones] = useState<string[]>([]);
  const [s3Error, setS3Error] = useState("");

  // Step 4 — Industry & Personas
  const [niche, setNiche] = useState("");
  const [personaTags, setPersonaTags] = useState<string[]>([]);
  const [s4Error, setS4Error] = useState("");

  // Step 5 — Delivery
  const [freq, setFreq] = useState<"daily" | "weekly">("daily");
  const [time, setTime] = useState("07:00");

  const totalSteps = 5;

  function toggleArr(arr: string[], val: string, set: (a: string[]) => void) {
    set(arr.includes(val) ? arr.filter((v) => v !== val) : [...arr, val]);
  }

  function choosePreset(preset: AvatarTypePreset | null) {
    setSelectedPreset(preset);
    if (preset) {
      setProfileName(preset.label);
      s1.reset({
        targetAgeMin: 18,
        targetAgeMax: 35,
        targetPlatforms: preset.target_platforms,
        targetRegions: preset.target_regions,
      });
      setGoals(preset.content_goals);
      setTones(preset.content_tones);
      setNiche(preset.industry_niche);
      setPersonaTags(preset.persona_tags);
    } else {
      setProfileName("My Profile");
    }
    setStep(1);
  }

  function onStep1(values: Step1) {
    void values; // already live in s1's form state, read directly at submit time
    setStep(2);
  }

  function onStep2Next() {
    setStep(3);
  }

  function onStep3Next() {
    if (goals.length === 0 || tones.length === 0) {
      setS3Error("Select at least one goal and one tone.");
      return;
    }
    setS3Error("");
    setStep(4);
  }

  function onStep4Next() {
    if (niche.trim().length < 3) {
      setS4Error("Describe your niche in a few words.");
      return;
    }
    setS4Error("");
    setStep(5);
  }

  async function onStep5Submit() {
    setSaving(true);
    setError("");

    const s1values = s1.getValues();
    const body: Omit<ContentProfile, "id" | "user_id" | "created_at"> = {
      name: profileName || "My Profile",
      industry_niche: niche,
      target_platforms: s1values.targetPlatforms,
      target_regions: s1values.targetRegions,
      content_goals: goals,
      content_tones: tones,
      persona_tags: personaTags,
      target_age_min: s1values.targetAgeMin,
      target_age_max: s1values.targetAgeMax,
      delivery_freq: freq,
      delivery_time: time,
      is_active: true,
      preferred_formats: preferredFormats,
    };

    try {
      const res = await fetch("/api/content-profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to save profile");
      router.push("/dashboard");
      router.refresh();
    } catch {
      setError("Failed to save your profile. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  const s1platforms = s1.watch("targetPlatforms") ?? [];
  const s1regions = s1.watch("targetRegions") ?? [];

  // ── Step 0 — Avatar type gallery ──────────────────────────────────────────
  if (step === 0) {
    return (
      <div className="w-full max-w-lg mx-auto">
        <div className="mb-6">
          <h2 className="text-xl font-bold text-gray-900">Choose a starting point</h2>
          <p className="text-sm text-gray-500 mt-1">
            Pre-fills a starting point based on durable, evergreen audiences — fully editable in every
            step after. Or start from scratch.
          </p>
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          {AVATAR_TYPES.map((preset) => (
            <button
              key={preset.key}
              type="button"
              onClick={() => choosePreset(preset)}
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
            onClick={() => choosePreset(null)}
            className="text-left rounded-xl border border-dashed border-gray-300 p-4 hover:border-blue-300 hover:bg-blue-50/50 transition-colors flex flex-col items-center justify-center gap-1 text-gray-400 hover:text-blue-600"
          >
            <Plus className="h-5 w-5" />
            <span className="text-xs font-medium">Start from scratch</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-lg mx-auto">
      {/* Progress */}
      <div className="flex items-center gap-2 mb-8">
        {Array.from({ length: totalSteps }).map((_, i) => (
          <div
            key={i}
            className={`h-1.5 flex-1 rounded-full transition-colors ${
              i + 1 <= step ? "bg-blue-600" : "bg-gray-200"
            }`}
          />
        ))}
      </div>

      {/* Step 1 — Audience */}
      {step === 1 && (
        <form onSubmit={s1.handleSubmit(onStep1)} className="space-y-6">
          <div>
            <h2 className="text-xl font-bold text-gray-900">Who is your audience?</h2>
            <p className="text-sm text-gray-500 mt-1">We&apos;ll filter trends to match them.</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-3">
              Age range:{" "}
              <span className="text-blue-600 font-semibold">
                {s1.watch("targetAgeMin")}–{s1.watch("targetAgeMax")}
              </span>
            </label>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-gray-400 mb-1">Min age</p>
                <input
                  type="range"
                  min={13}
                  max={65}
                  {...s1.register("targetAgeMin", { valueAsNumber: true })}
                  className="w-full accent-blue-600"
                />
              </div>
              <div>
                <p className="text-xs text-gray-400 mb-1">Max age</p>
                <input
                  type="range"
                  min={13}
                  max={65}
                  {...s1.register("targetAgeMax", { valueAsNumber: true })}
                  className="w-full accent-blue-600"
                />
              </div>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-3">Target platforms</label>
            <div className="flex flex-wrap gap-2">
              {PLATFORMS.map((p) => (
                <Chip
                  key={p}
                  label={p}
                  selected={s1platforms.includes(p)}
                  onClick={() => {
                    const next = s1platforms.includes(p)
                      ? s1platforms.filter((v) => v !== p)
                      : [...s1platforms, p];
                    s1.setValue("targetPlatforms", next, { shouldValidate: true });
                  }}
                />
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-1.5">
              {IDEAS_ONLY_PLATFORMS.join(", ")}: content ideas only — connecting an account, publishing, and tracking aren&apos;t available for these yet.
            </p>
            {s1.formState.errors.targetPlatforms && (
              <p className="text-xs text-red-500 mt-1">{s1.formState.errors.targetPlatforms.message}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-3">Target regions</label>
            <RegionChips
              selected={s1regions}
              onChange={(next) => s1.setValue("targetRegions", next, { shouldValidate: true })}
            />
            {s1.formState.errors.targetRegions && (
              <p className="text-xs text-red-500 mt-1">{s1.formState.errors.targetRegions.message}</p>
            )}
          </div>

          <button
            type="submit"
            className="w-full bg-blue-600 text-white font-semibold py-3 rounded-xl hover:bg-blue-700 transition-colors"
          >
            Next: Content format
          </button>
        </form>
      )}

      {/* Step 2 — Preferred content format */}
      {step === 2 && (
        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-bold text-gray-900">What kind of content do you make?</h2>
            <p className="text-sm text-gray-500 mt-1">
              Ideas and generation tools will focus on these — you can change this anytime in Settings.
            </p>
          </div>

          <div className="grid gap-3">
            {CONTENT_FORMATS.map((f) => {
              const selected = preferredFormats.includes(f.key);
              return (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => toggleArr(preferredFormats, f.key, setPreferredFormats)}
                  className={`text-left rounded-xl border-2 p-4 transition-all ${
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

          <div className="flex gap-3">
            <button
              onClick={() => setStep(1)}
              className="flex-1 border border-gray-200 text-gray-600 font-semibold py-3 rounded-xl hover:bg-gray-50 transition-colors"
            >
              Back
            </button>
            <button
              onClick={onStep2Next}
              className="flex-1 bg-blue-600 text-white font-semibold py-3 rounded-xl hover:bg-blue-700 transition-colors"
            >
              Next: Goals & Tone
            </button>
          </div>
        </div>
      )}

      {/* Step 3 — Goals & Tone */}
      {step === 3 && (
        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-bold text-gray-900">What do you want to achieve?</h2>
            <p className="text-sm text-gray-500 mt-1">Your content goals and brand voice.</p>
          </div>

          {s3Error && (
            <p className="text-xs text-red-500 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{s3Error}</p>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-3">Content goals</label>
            <div className="flex flex-wrap gap-2">
              {CONTENT_GOALS.map((g) => (
                <Chip key={g} label={g} selected={goals.includes(g)} onClick={() => toggleArr(goals, g, setGoals)} />
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-3">Content tone</label>
            <div className="grid grid-cols-2 gap-3">
              {CONTENT_TONES.map((t) => (
                <ToneCard key={t} label={t} selected={tones.includes(t)} onClick={() => toggleArr(tones, t, setTones)} />
              ))}
            </div>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => setStep(2)}
              className="flex-1 border border-gray-200 text-gray-600 font-semibold py-3 rounded-xl hover:bg-gray-50 transition-colors"
            >
              Back
            </button>
            <button
              onClick={onStep3Next}
              className="flex-1 bg-blue-600 text-white font-semibold py-3 rounded-xl hover:bg-blue-700 transition-colors"
            >
              Next: Industry
            </button>
          </div>
        </div>
      )}

      {/* Step 4 — Industry & Personas */}
      {step === 4 && (
        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-bold text-gray-900">Your niche & audience personas</h2>
            <p className="text-sm text-gray-500 mt-1">
              This lets us filter trends by cultural subgroups your audience belongs to.
            </p>
          </div>

          {s4Error && (
            <p className="text-xs text-red-500 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{s4Error}</p>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Industry / niche</label>
            <input
              type="text"
              value={niche}
              onChange={(e) => setNiche(e.target.value)}
              placeholder="e.g. Luxury skincare, Streetwear, Fitness supplements"
              className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none transition"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-3">
              Audience persona tags{" "}
              <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <PersonaChips selected={personaTags} onChange={setPersonaTags} />
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => setStep(3)}
              className="flex-1 border border-gray-200 text-gray-600 font-semibold py-3 rounded-xl hover:bg-gray-50 transition-colors"
            >
              Back
            </button>
            <button
              onClick={onStep4Next}
              className="flex-1 bg-blue-600 text-white font-semibold py-3 rounded-xl hover:bg-blue-700 transition-colors"
            >
              Next: Delivery
            </button>
          </div>
        </div>
      )}

      {/* Step 5 — Delivery */}
      {step === 5 && (
        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-bold text-gray-900">When do you want your digest?</h2>
            <p className="text-sm text-gray-500 mt-1">Your content ideas will arrive on schedule.</p>
          </div>

          {error && (
            <p className="text-xs text-red-500 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-3">Frequency</label>
            <div className="grid grid-cols-2 gap-3">
              {(["daily", "weekly"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFreq(f)}
                  className={`rounded-xl border-2 py-4 text-sm font-semibold capitalize transition-all ${
                    freq === f
                      ? "border-blue-600 bg-blue-50 text-blue-700"
                      : "border-gray-200 text-gray-600 hover:border-blue-200"
                  }`}
                >
                  {f === "daily" ? "Daily (recommended)" : "Weekly"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Delivery time (your local timezone)
            </label>
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none transition"
            />
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => setStep(4)}
              className="flex-1 border border-gray-200 text-gray-600 font-semibold py-3 rounded-xl hover:bg-gray-50 transition-colors"
            >
              Back
            </button>
            <button
              onClick={onStep5Submit}
              disabled={saving}
              className="flex-1 bg-blue-600 text-white font-semibold py-3 rounded-xl hover:bg-blue-700 disabled:opacity-60 transition-colors flex items-center justify-center gap-2"
            >
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              {saving ? "Saving..." : "Launch my dashboard"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

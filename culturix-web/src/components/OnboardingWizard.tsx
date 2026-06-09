"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, Check } from "lucide-react";
import {
  PLATFORMS,
  REGIONS,
  CONTENT_GOALS,
  CONTENT_TONES,
  PERSONA_TAGS,
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

const step2Schema = z.object({
  contentGoals: z.array(z.string()).min(1, "Select at least one goal"),
  contentTones: z.array(z.string()).min(1, "Select at least one tone"),
});

const step3Schema = z.object({
  industryNiche: z.string().min(3, "Describe your niche in a few words"),
  personaTags: z.array(z.string()),
});

const step4Schema = z.object({
  deliveryFreq: z.enum(["daily", "weekly"]),
  deliveryTime: z.string(),
});

type Step1 = z.infer<typeof step1Schema>;
type Step2 = z.infer<typeof step2Schema>;
type Step3 = z.infer<typeof step3Schema>;
type Step4 = z.infer<typeof step4Schema>;

interface Props {
  userId: string;
}

export default function OnboardingWizard({ userId }: Props) {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const [data, setData] = useState<Partial<UserProfile>>({
    user_id: userId,
    targetAgeMin: 18,
    targetAgeMax: 35,
    targetPlatforms: [],
    targetRegions: [],
    contentGoals: [],
    contentTones: [],
    industryNiche: "",
    personaTags: [],
    deliveryFreq: "daily",
    deliveryTime: "07:00",
  } as unknown as Partial<UserProfile>);

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

  // Step 2
  const [goals, setGoals] = useState<string[]>([]);
  const [tones, setTones] = useState<string[]>([]);
  const [s2Error, setS2Error] = useState("");

  // Step 3
  const [niche, setNiche] = useState("");
  const [personaTags, setPersonaTags] = useState<string[]>([]);
  const [s3Error, setS3Error] = useState("");

  // Step 4
  const [freq, setFreq] = useState<"daily" | "weekly">("daily");
  const [time, setTime] = useState("07:00");

  const totalSteps = 4;

  function toggleArr(arr: string[], val: string, set: (a: string[]) => void) {
    set(arr.includes(val) ? arr.filter((v) => v !== val) : [...arr, val]);
  }

  async function onStep1(values: Step1) {
    setData((d) => ({
      ...d,
      target_age_min: values.targetAgeMin,
      target_age_max: values.targetAgeMax,
      target_platforms: values.targetPlatforms,
      target_regions: values.targetRegions,
    }));
    setStep(2);
  }

  function onStep2Next() {
    if (goals.length === 0 || tones.length === 0) {
      setS2Error("Select at least one goal and one tone.");
      return;
    }
    setS2Error("");
    setData((d) => ({ ...d, content_goals: goals, content_tones: tones }));
    setStep(3);
  }

  function onStep3Next() {
    if (niche.trim().length < 3) {
      setS3Error("Describe your niche in a few words.");
      return;
    }
    setS3Error("");
    setData((d) => ({ ...d, industry_niche: niche, persona_tags: personaTags }));
    setStep(4);
  }

  async function onStep4Submit() {
    setSaving(true);
    setError("");
    const profile: UserProfile = {
      ...(data as UserProfile),
      user_id: userId,
      delivery_freq: freq,
      delivery_time: time,
    };

    try {
      const res = await fetch("/api/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      if (!res.ok) throw new Error("Failed to save profile");
      router.push("/dashboard");
      router.refresh();
    } catch (err) {
      setError("Failed to save your profile. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  const s1platforms = s1.watch("targetPlatforms") ?? [];
  const s1regions = s1.watch("targetRegions") ?? [];

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
            {s1.formState.errors.targetPlatforms && (
              <p className="text-xs text-red-500 mt-1">{s1.formState.errors.targetPlatforms.message}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-3">Target regions</label>
            <div className="flex flex-wrap gap-2">
              {REGIONS.map((r) => (
                <Chip
                  key={r}
                  label={r}
                  selected={s1regions.includes(r)}
                  onClick={() => {
                    const next = s1regions.includes(r)
                      ? s1regions.filter((v) => v !== r)
                      : [...s1regions, r];
                    s1.setValue("targetRegions", next, { shouldValidate: true });
                  }}
                />
              ))}
            </div>
            {s1.formState.errors.targetRegions && (
              <p className="text-xs text-red-500 mt-1">{s1.formState.errors.targetRegions.message}</p>
            )}
          </div>

          <button
            type="submit"
            className="w-full bg-blue-600 text-white font-semibold py-3 rounded-xl hover:bg-blue-700 transition-colors"
          >
            Next: Goals & Tone
          </button>
        </form>
      )}

      {/* Step 2 — Goals & Tone */}
      {step === 2 && (
        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-bold text-gray-900">What do you want to achieve?</h2>
            <p className="text-sm text-gray-500 mt-1">Your content goals and brand voice.</p>
          </div>

          {s2Error && (
            <p className="text-xs text-red-500 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{s2Error}</p>
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
              onClick={() => setStep(1)}
              className="flex-1 border border-gray-200 text-gray-600 font-semibold py-3 rounded-xl hover:bg-gray-50 transition-colors"
            >
              Back
            </button>
            <button
              onClick={onStep2Next}
              className="flex-1 bg-blue-600 text-white font-semibold py-3 rounded-xl hover:bg-blue-700 transition-colors"
            >
              Next: Industry
            </button>
          </div>
        </div>
      )}

      {/* Step 3 — Industry & Personas */}
      {step === 3 && (
        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-bold text-gray-900">Your niche & audience personas</h2>
            <p className="text-sm text-gray-500 mt-1">
              This lets us filter trends by cultural subgroups your audience belongs to.
            </p>
          </div>

          {s3Error && (
            <p className="text-xs text-red-500 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{s3Error}</p>
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
            <div className="flex flex-wrap gap-2">
              {PERSONA_TAGS.map((t) => (
                <Chip
                  key={t}
                  label={t}
                  selected={personaTags.includes(t)}
                  onClick={() => toggleArr(personaTags, t, setPersonaTags)}
                />
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
              Next: Delivery
            </button>
          </div>
        </div>
      )}

      {/* Step 4 — Delivery */}
      {step === 4 && (
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
              onClick={() => setStep(3)}
              className="flex-1 border border-gray-200 text-gray-600 font-semibold py-3 rounded-xl hover:bg-gray-50 transition-colors"
            >
              Back
            </button>
            <button
              onClick={onStep4Submit}
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

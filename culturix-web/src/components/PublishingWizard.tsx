"use client";

import { useEffect, useState } from "react";
import { Loader2, X, Link2, ArrowRight, Info } from "lucide-react";
import type { ContentProfile, ConnectedAccount, NextAutoPublish } from "@/lib/types";
import { WHY_NOT_DIRECT_PUBLISH, IOS_PUSH_NOTE, PUBLISH_MODE_DESCRIPTIONS, PUBLISH_MODE_LABELS } from "@/content/publishingCopy";
import ConnectionTestPanel, { type ConnectionTestResult } from "@/components/publish/ConnectionTestPanel";

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

type Step = "connect" | "test" | "mode" | "next";

// These three have never been exercised against a live account (see each
// provider file's own docstring) — the Test step is exactly the mechanism
// that will surface a real problem if one exists, so flag rather than hide.
const BETA_PLATFORMS = new Set(["tiktok", "instagram", "twitter"]);

interface Props {
  userId: string;
  profile: ContentProfile;
  platform: ConnectedAccount["platform"];
  platformLabel: string;
  connectedAccounts: ConnectedAccount[];
  initialStep?: Step;
  onAccountsChanged: () => void;
  onModeChange: (mode: "manual" | "review" | "auto") => Promise<void> | void;
  onClose: () => void;
}

const STEPS: { key: Step; label: string }[] = [
  { key: "connect", label: "Connect" },
  { key: "test", label: "Test" },
  { key: "mode", label: "Publish mode" },
  { key: "next", label: "What's next" },
];

export default function PublishingWizard({
  userId, profile, platform, platformLabel, connectedAccounts,
  initialStep = "connect", onAccountsChanged, onModeChange, onClose,
}: Props) {
  const account = connectedAccounts.find(
    a => a.platform === platform && a.status === "active" && a.content_profile_id === profile.id
  );
  const [step, setStep] = useState<Step>(account ? initialStep : "connect");
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [mode, setMode] = useState<"manual" | "review" | "auto">(profile.publish_mode ?? "manual");
  const [modeSaving, setModeSaving] = useState(false);
  const [nextPreview, setNextPreview] = useState<NextAutoPublish | null>(null);
  const [nextLoading, setNextLoading] = useState(false);

  const isBeta = BETA_PLATFORMS.has(platform);

  useEffect(() => {
    if (account && step === "connect") setStep("test");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account]);

  async function runConnectionTest(): Promise<ConnectionTestResult> {
    const res = await fetch(
      `${RAILWAY}/api/social/${platform}/test?user_id=${userId}&content_profile_id=${profile.id}`,
      { method: "POST" }
    );
    return await res.json().catch(() => ({ ok: false }));
  }

  async function saveMode() {
    setModeSaving(true);
    try {
      await onModeChange(mode);
      setStep("next");
      if (mode === "auto") {
        setNextLoading(true);
        try {
          const res = await fetch(`/api/content-profiles/${profile.id}/next-auto-publish`);
          if (res.ok) setNextPreview(await res.json());
        } catch {
          // leave nextPreview null — the empty state below covers this
        } finally {
          setNextLoading(false);
        }
      }
    } finally {
      setModeSaving(false);
    }
  }

  const activeStepIndex = STEPS.findIndex(s => s.key === step);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl bg-white shadow-xl p-6 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="font-semibold text-gray-900">Set up publishing — {platformLabel}</h2>
            <p className="text-xs text-gray-400 mt-0.5">for &ldquo;{profile.name || "this profile"}&rdquo;</p>
          </div>
          <button onClick={onClose} className="text-gray-300 hover:text-gray-500">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div>
          <div className="flex items-center gap-1.5">
            {STEPS.map((s, i) => (
              <div
                key={s.key}
                className={`h-1.5 flex-1 rounded-full ${activeStepIndex >= i ? "bg-primary-600" : "bg-gray-100"}`}
              />
            ))}
          </div>
          <p className="text-xs font-medium text-gray-400 mt-1.5">{STEPS[activeStepIndex].label}</p>
        </div>

        {isBeta && (
          <p className="flex items-start gap-1.5 text-xs text-amber-600 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
            <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            Beta — this integration hasn&apos;t been verified against a live account yet. The Test
            step below is exactly how we&apos;ll find out if something&apos;s wrong.
          </p>
        )}

        {step === "connect" && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Connect the dedicated {platformLabel} account you run for this niche.
            </p>
            <a
              href={`${RAILWAY}/api/social/${platform}/connect?user_id=${userId}&content_profile_id=${profile.id}`}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary-600 text-white font-semibold py-3 hover:bg-primary-700 transition"
            >
              <Link2 className="h-4 w-4" /> Connect {platformLabel}
            </a>
          </div>
        )}

        {step === "test" && (
          <div className="space-y-3">
            <ConnectionTestPanel
              description={`Confirm this connection actually works before relying on it — a quick live check against ${platformLabel}.`}
              lastTestedAt={account?.last_tested_at}
              lastTestStatus={account?.last_test_status}
              testResult={testResult}
              runTest={runConnectionTest}
              onResult={setTestResult}
              onTested={onAccountsChanged}
            />
            <div className="flex items-center justify-between pt-1">
              <button onClick={() => setStep("connect")} className="text-xs text-gray-400 hover:text-gray-600">
                Back
              </button>
              <button
                onClick={() => setStep("mode")}
                className="inline-flex items-center gap-1 text-sm font-medium text-primary-600 hover:text-primary-700"
              >
                Continue <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}

        {step === "mode" && (
          <div className="space-y-3">
            <p className="text-xs text-gray-500 bg-gray-50 border border-gray-100 rounded-lg px-3 py-2">
              {WHY_NOT_DIRECT_PUBLISH}{" "}
              <a href="/how-it-works" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline whitespace-nowrap">
                Learn more →
              </a>
            </p>
            {testResult && !testResult.ok && (
              <p className="text-xs text-amber-600 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                The last test didn&apos;t pass — Review/Auto may not work until this is fixed, but
                you can still choose a mode now and fix the connection later.
              </p>
            )}
            <div className="grid grid-cols-3 gap-2">
              {(["manual", "review", "auto"] as const).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setMode(key)}
                  className={`text-left rounded-xl border-2 p-3 transition-all ${
                    mode === key ? "border-primary-600 bg-primary-50" : "border-gray-200"
                  }`}
                >
                  <p className={`text-xs font-semibold ${mode === key ? "text-primary-700" : "text-gray-700"}`}>{PUBLISH_MODE_LABELS[key]}</p>
                  <p className="text-xs text-gray-400 mt-1">{PUBLISH_MODE_DESCRIPTIONS[key]}</p>
                </button>
              ))}
            </div>
            <div className="flex items-center justify-between pt-1">
              <button onClick={() => setStep("test")} className="text-xs text-gray-400 hover:text-gray-600">
                Back
              </button>
              <button
                onClick={saveMode}
                disabled={modeSaving}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 text-white px-4 py-2 text-sm font-medium hover:bg-primary-700 disabled:opacity-60"
              >
                {modeSaving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Save & continue
              </button>
            </div>
          </div>
        )}

        {step === "next" && (
          <div className="space-y-3">
            {(mode === "review" || mode === "auto") && (
              <p className="text-xs text-gray-500 bg-gray-50 border border-gray-100 rounded-lg px-3 py-2">
                {IOS_PUSH_NOTE}
              </p>
            )}
            {mode === "manual" && (
              <p className="text-sm text-gray-600">
                You&apos;re set. Post ideas yourself whenever you&apos;re ready, then use{" "}
                <span className="font-medium">Mark as posted</span> on the dashboard to track
                performance here.
              </p>
            )}
            {mode === "review" && (
              <p className="text-sm text-gray-600">
                You&apos;re set. Eligible ideas on your dashboard now have a{" "}
                <span className="font-medium">Stage &amp; notify me</span> button — Culturix preps
                it (video rendered, caption written) and pings you the moment it&apos;s ready to
                launch.
              </p>
            )}
            {mode === "auto" && (
              <div className="space-y-2">
                <p className="text-sm text-gray-600">
                  You&apos;re set. Once a day, Culturix preps your best idea — video rendered,
                  caption written — and sends you a notification. Tap it to launch: video saved,
                  caption copied, the app opened. You do the final tap-to-post yourself, from your
                  own account, so nothing about your trending-audio access changes.
                </p>
                {nextLoading ? (
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking next candidate…
                  </div>
                ) : nextPreview?.candidate ? (
                  <div className="rounded-lg bg-primary-50 border border-primary-100 px-3 py-2.5">
                    <p className="text-xs font-semibold text-primary-700">
                      Next up: &ldquo;{nextPreview.candidate.hook}&rdquo;
                    </p>
                    <p className="text-xs text-primary-500 mt-0.5">
                      on {nextPreview.candidate.platform} — {nextPreview.scheduled_for}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      Subject to change before then — new ideas or status updates can affect what
                      actually gets picked.
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-gray-400">
                    Nothing eligible to auto-publish yet — check back once today&apos;s ideas are ready.
                  </p>
                )}
              </div>
            )}
            <button
              onClick={onClose}
              className="w-full rounded-xl bg-primary-600 text-white font-semibold py-3 hover:bg-primary-700 transition"
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

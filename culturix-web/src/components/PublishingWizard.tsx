"use client";

import { useEffect, useState } from "react";
import { Loader2, X, Link2, ShieldCheck, ShieldAlert, ArrowRight, Info } from "lucide-react";
import type { ContentProfile, ConnectedAccount, NextAutoPublish } from "@/lib/types";

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
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; reason?: string; platform_username?: string } | null>(null);
  const [mode, setMode] = useState<"manual" | "review" | "auto">(profile.publish_mode ?? "manual");
  const [modeSaving, setModeSaving] = useState(false);
  const [nextPreview, setNextPreview] = useState<NextAutoPublish | null>(null);
  const [nextLoading, setNextLoading] = useState(false);

  const isBeta = BETA_PLATFORMS.has(platform);

  useEffect(() => {
    if (account && step === "connect") setStep("test");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account]);

  async function runTest() {
    if (testing) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch(
        `${RAILWAY}/api/social/${platform}/test?user_id=${userId}&content_profile_id=${profile.id}`,
        { method: "POST" }
      );
      const data = await res.json().catch(() => ({ ok: false }));
      setTestResult(data);
      onAccountsChanged();
    } catch {
      setTestResult({ ok: false, reason: "Network error — try again." });
    } finally {
      setTesting(false);
    }
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
                className={`h-1.5 flex-1 rounded-full ${activeStepIndex >= i ? "bg-blue-600" : "bg-gray-100"}`}
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
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-blue-600 text-white font-semibold py-3 hover:bg-blue-700 transition"
            >
              <Link2 className="h-4 w-4" /> Connect {platformLabel}
            </a>
          </div>
        )}

        {step === "test" && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Confirm this connection actually works before relying on it — a quick live check
              against {platformLabel}.
            </p>
            {account?.last_tested_at && !testResult && (
              <p className="text-xs text-gray-400">
                Last tested {new Date(account.last_tested_at).toLocaleString()} —{" "}
                {account.last_test_status === "ok" ? "passed" : "failed"}
              </p>
            )}
            <button
              onClick={runTest}
              disabled={testing}
              className="w-full flex items-center justify-center gap-2 rounded-xl border border-gray-200 py-3 text-sm font-semibold text-gray-700 hover:border-blue-300 hover:text-blue-600 disabled:opacity-60 transition"
            >
              {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
              {testing ? "Testing…" : testResult ? "Test again" : "Test connection"}
            </button>
            {testResult && (
              <div
                className={`flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm ${
                  testResult.ok ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"
                }`}
              >
                {testResult.ok
                  ? <ShieldCheck className="h-4 w-4 mt-0.5 shrink-0" />
                  : <ShieldAlert className="h-4 w-4 mt-0.5 shrink-0" />}
                <span>
                  {testResult.ok
                    ? `Connected as @${testResult.platform_username ?? "your account"} — working.`
                    : testResult.reason ?? "Could not verify this connection."}
                </span>
              </div>
            )}
            <div className="flex items-center justify-between pt-1">
              <button onClick={() => setStep("connect")} className="text-xs text-gray-400 hover:text-gray-600">
                Back
              </button>
              <button
                onClick={() => setStep("mode")}
                className="inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-700"
              >
                Continue <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}

        {step === "mode" && (
          <div className="space-y-3">
            {testResult && !testResult.ok && (
              <p className="text-xs text-amber-600 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                The last test didn&apos;t pass — Review/Auto may not work until this is fixed, but
                you can still choose a mode now and fix the connection later.
              </p>
            )}
            <div className="grid grid-cols-3 gap-2">
              {([
                { key: "manual", label: "Manual", desc: "You post it yourself, then paste the link to track it." },
                { key: "review", label: "Review", desc: "Click Publish on an idea — Culturix posts it for you." },
                { key: "auto", label: "Auto", desc: "Culturix publishes the best idea on its own, once a day." },
              ] as const).map(({ key, label, desc }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setMode(key)}
                  className={`text-left rounded-xl border-2 p-3 transition-all ${
                    mode === key ? "border-blue-600 bg-blue-50" : "border-gray-200"
                  }`}
                >
                  <p className={`text-xs font-semibold ${mode === key ? "text-blue-700" : "text-gray-700"}`}>{label}</p>
                  <p className="text-xs text-gray-400 mt-1">{desc}</p>
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
                className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-60"
              >
                {modeSaving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Save & continue
              </button>
            </div>
          </div>
        )}

        {step === "next" && (
          <div className="space-y-3">
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
                <span className="font-medium">Publish</span> button — Culturix posts it the moment
                you click.
              </p>
            )}
            {mode === "auto" && (
              <div className="space-y-2">
                <p className="text-sm text-gray-600">
                  You&apos;re set. Culturix will publish automatically, once a day.
                </p>
                {nextLoading ? (
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking next candidate…
                  </div>
                ) : nextPreview?.candidate ? (
                  <div className="rounded-lg bg-blue-50 border border-blue-100 px-3 py-2.5">
                    <p className="text-xs font-semibold text-blue-700">
                      Next up: &ldquo;{nextPreview.candidate.hook}&rdquo;
                    </p>
                    <p className="text-xs text-blue-500 mt-0.5">
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
              className="w-full rounded-xl bg-blue-600 text-white font-semibold py-3 hover:bg-blue-700 transition"
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { X, Link2, ArrowRight } from "lucide-react";
import type { ConnectedAccount } from "@/lib/types";
import ConnectionTestPanel, { type ConnectionTestResult } from "@/components/publish/ConnectionTestPanel";

type Step = "connect" | "test" | "done";

interface Props {
  brandId: string;
  brandName: string;
  platform: ConnectedAccount["platform"];
  platformLabel: string;
  connectedAccounts: ConnectedAccount[];
  onAccountsChanged: () => void;
  onClose: () => void;
}

const STEPS: { key: Step; label: string }[] = [
  { key: "connect", label: "Connect" },
  { key: "test", label: "Test" },
  { key: "done", label: "Done" },
];

// CultureToons publishes directly (see ToonManager's Publish button) rather
// than through the trend engine's manual/review/auto cadence — so unlike
// PublishingWizard.tsx, this wizard has no "mode" step, just connect+test.
export default function CultureToonPublishPanel({
  brandId, brandName, platform, platformLabel, connectedAccounts, onAccountsChanged, onClose,
}: Props) {
  const account = connectedAccounts.find((a) => a.platform === platform && a.status === "active");
  const [step, setStep] = useState<Step>(account ? "test" : "connect");
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  useEffect(() => {
    if (account && step === "connect") setStep("test");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account]);

  async function runConnectionTest(): Promise<ConnectionTestResult> {
    const res = await fetch(`/api/culturetoons/social/${platform}/test?brand_id=${brandId}`, { method: "POST" });
    return await res.json().catch(() => ({ ok: false }));
  }

  const activeStepIndex = STEPS.findIndex((s) => s.key === step);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl bg-white shadow-xl p-6 space-y-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="font-semibold text-gray-900">Connect {platformLabel}</h2>
            <p className="text-xs text-gray-400 mt-0.5">for &ldquo;{brandName}&rdquo;</p>
          </div>
          <button onClick={onClose} className="text-gray-300 hover:text-gray-500">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div>
          <div className="flex items-center gap-1.5">
            {STEPS.map((s, i) => (
              <div key={s.key} className={`h-1.5 flex-1 rounded-full ${activeStepIndex >= i ? "bg-primary-600" : "bg-gray-100"}`} />
            ))}
          </div>
          <p className="text-xs font-medium text-gray-400 mt-1.5">{STEPS[activeStepIndex].label}</p>
        </div>

        {step === "connect" && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Connect the {platformLabel} account this toon brand should post to.
            </p>
            <a
              href={`/api/culturetoons/social/${platform}/connect?brand_id=${brandId}`}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary-600 text-white font-semibold py-3 hover:bg-primary-700 transition"
            >
              <Link2 className="h-4 w-4" /> Connect {platformLabel}
            </a>
          </div>
        )}

        {step === "test" && (
          <div className="space-y-3">
            <ConnectionTestPanel
              description="Confirm this connection actually works before publishing to it."
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
                onClick={() => setStep("done")}
                className="inline-flex items-center gap-1 text-sm font-medium text-primary-600 hover:text-primary-700"
              >
                Continue <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}

        {step === "done" && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              You&apos;re set — this brand can now publish directly to {platformLabel} from the Toons tab.
            </p>
            <button onClick={onClose} className="w-full rounded-xl bg-primary-600 text-white font-semibold py-3 hover:bg-primary-700 transition">
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

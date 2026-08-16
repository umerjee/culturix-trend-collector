"use client";

import { useState } from "react";
import { Loader2, ShieldCheck, ShieldAlert } from "lucide-react";

export interface ConnectionTestResult {
  ok: boolean;
  reason?: string;
  platform_username?: string;
}

interface Props {
  description: string;
  lastTestedAt?: string | null;
  lastTestStatus?: string | null;
  testResult: ConnectionTestResult | null;
  runTest: () => Promise<ConnectionTestResult>;
  // Test result ownership stays with the caller (PublishingWizard needs it
  // for a later step's warning banner; CultureToonPublishPanel doesn't) —
  // this component only owns the transient "testing" spinner state.
  onResult: (result: ConnectionTestResult) => void;
  onTested: () => void;
}

// Extracted shared slice of PublishingWizard.tsx and CultureToonPublishPanel.tsx
// — both independently implemented this same "test connection → status pill
// → result message" UI. The surrounding connect/mode/done step flow in each
// stays in its own file; only this piece was actually identical.
export default function ConnectionTestPanel({
  description, lastTestedAt, lastTestStatus, testResult, runTest, onResult, onTested,
}: Props) {
  const [testing, setTesting] = useState(false);

  async function handleTest() {
    if (testing) return;
    setTesting(true);
    try {
      const result = await runTest();
      onResult(result);
      onTested();
    } catch {
      onResult({ ok: false, reason: "Network error — try again." });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-600">{description}</p>
      {lastTestedAt && !testResult && (
        <p className="text-xs text-gray-400">
          Last tested {new Date(lastTestedAt).toLocaleString()} —{" "}
          {lastTestStatus === "ok" ? "passed" : "failed"}
        </p>
      )}
      <button
        onClick={handleTest}
        disabled={testing}
        className="w-full flex items-center justify-center gap-2 rounded-xl border border-gray-200 py-3 text-sm font-semibold text-gray-700 hover:border-primary-300 hover:text-primary-600 disabled:opacity-60 transition"
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
    </div>
  );
}

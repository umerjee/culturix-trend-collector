"use client";

import { useEffect, useState } from "react";
import { Link2, ShieldCheck } from "lucide-react";
import type { ConnectedAccount } from "@/lib/types";
import { CONNECTABLE_PLATFORMS } from "@/lib/types";
import CultureToonPublishPanel from "@/components/CultureToonPublishPanel";

interface Props {
  brandId: string;
  brandName: string;
  // Restricts which platform chips show (e.g. a brand's own target_platforms
  // during onboarding) — defaults to every connectable platform, which is
  // what ToonManager's own "Connected accounts" step wants.
  platforms?: string[];
  onAccountsLoaded?: (accounts: ConnectedAccount[]) => void;
}

// Shared by ToonManager's "Connect accounts" step and CultureToonApp's
// post-brand-creation onboarding step — factored out so both render the
// exact same chip-row + connect/test wizard instead of drifting apart.
export default function ConnectedAccountsPanel({ brandId, brandName, platforms, onAccountsLoaded }: Props) {
  const [connectedAccounts, setConnectedAccounts] = useState<ConnectedAccount[]>([]);
  const [connectPanelPlatform, setConnectPanelPlatform] = useState<ConnectedAccount["platform"] | null>(null);

  async function loadConnectedAccounts() {
    const res = await fetch(`/api/culturetoons/social/accounts?brand_id=${brandId}`, { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      setConnectedAccounts(data);
      onAccountsLoaded?.(data);
    }
  }

  useEffect(() => {
    loadConnectedAccounts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  const shownPlatforms = platforms && platforms.length > 0
    ? CONNECTABLE_PLATFORMS.filter((p) => platforms.includes(p.key))
    : CONNECTABLE_PLATFORMS;

  return (
    <>
      <div className="flex flex-wrap gap-1.5">
        {shownPlatforms.map((p) => {
          const acct = connectedAccounts.find((a) => a.platform === p.key && a.status === "active");
          return (
            <button
              key={p.key}
              onClick={() => setConnectPanelPlatform(p.key as ConnectedAccount["platform"])}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                acct ? "bg-green-50 border-green-200 text-green-700" : "bg-white border-gray-200 text-gray-500 hover:border-blue-300"
              }`}
            >
              {acct ? <ShieldCheck className="h-3 w-3" /> : <Link2 className="h-3 w-3" />}
              {p.display}
              {acct?.platform_username && <span className="text-green-500">@{acct.platform_username}</span>}
            </button>
          );
        })}
      </div>

      {connectPanelPlatform && (
        <CultureToonPublishPanel
          brandId={brandId}
          brandName={brandName}
          platform={connectPanelPlatform}
          platformLabel={CONNECTABLE_PLATFORMS.find((p) => p.key === connectPanelPlatform)?.display ?? connectPanelPlatform}
          connectedAccounts={connectedAccounts}
          onAccountsChanged={loadConnectedAccounts}
          onClose={() => setConnectPanelPlatform(null)}
        />
      )}
    </>
  );
}

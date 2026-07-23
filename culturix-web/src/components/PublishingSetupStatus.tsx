"use client";

import { useState } from "react";
import { Check, Circle, ChevronDown, ChevronUp, Link2, ArrowRight } from "lucide-react";

export interface PlatformStatus {
  key: string;
  label: string;
  connected: boolean;
  verified: boolean;
}

const MODE_LABEL: Record<string, string> = {
  manual: "Manual", review: "Review", auto: "Auto",
};

interface BaseProps {
  platforms: PlatformStatus[];
  publishMode: "manual" | "review" | "auto";
  hasContentReady: boolean;
  hasConfirmedPost: boolean;
}

interface CompactProps extends BaseProps {
  variant: "compact";
  settingsHref: string;
}

interface FullProps extends BaseProps {
  variant: "full";
  onManagePlatform: (platformKey: string) => void;
  onChangeMode: () => void;
}

type Props = CompactProps | FullProps;

// Deliberately no persisted "completed" state anywhere in this component —
// every render recomputes from the platforms/mode/content props passed in,
// which are themselves always freshly fetched by the caller. Disconnect an
// account or lose your only staged post and this reflects that on the very
// next render, with no stale "you already did this" flag to clear.
function isComplete(p: BaseProps): boolean {
  return (
    p.platforms.length > 0 &&
    p.platforms.every((pl) => pl.connected && pl.verified) &&
    p.hasContentReady &&
    p.hasConfirmedPost
  );
}

export default function PublishingSetupStatus(props: Props) {
  const [expanded, setExpanded] = useState(!isComplete(props));

  if (props.variant === "compact") {
    if (isComplete(props)) return null; // Dashboard only nudges when something's missing
    const verifiedCount = props.platforms.filter((p) => p.connected && p.verified).length;
    const parts = [
      `${verifiedCount}/${props.platforms.length} platform${props.platforms.length === 1 ? "" : "s"} connected`,
      `${MODE_LABEL[props.publishMode]} mode`,
      !props.hasContentReady
        ? "no content ready yet"
        : !props.hasConfirmedPost
        ? "nothing confirmed yet"
        : null,
    ].filter(Boolean);
    return (
      <a
        href={props.settingsHref}
        className="mb-6 -mt-2 flex flex-wrap items-center justify-between gap-x-2 gap-y-1 rounded-xl bg-amber-50 border border-amber-100 px-4 py-3 text-xs text-amber-700 hover:border-amber-200 transition-colors"
      >
        <span className="flex-1 min-w-[14rem]">
          <span className="font-semibold">Finish setting up publishing</span> — {parts.join(" · ")}
        </span>
        <span className="inline-flex items-center gap-1 font-medium shrink-0">
          Finish in Settings <ArrowRight className="h-3 w-3" />
        </span>
      </a>
    );
  }

  const complete = isComplete(props);

  return (
    <section className="bg-white rounded-2xl border border-gray-100 p-6 mb-6">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <h2 className="font-semibold text-gray-900">
          {complete ? "✓ Publishing set up" : "Publishing setup"}
        </h2>
        {expanded ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
      </button>

      {expanded && (
        <div className="mt-4 space-y-3">
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-gray-500">Connect &amp; verify an account</p>
            {props.platforms.length === 0 ? (
              <p className="text-xs text-gray-400">
                No connectable platforms selected for this profile yet — add one in Audience above.
              </p>
            ) : (
              props.platforms.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => props.onManagePlatform(p.key)}
                  className="w-full flex items-center justify-between gap-2 rounded-lg border border-gray-100 px-3 py-2 hover:border-blue-200 transition-colors text-left"
                >
                  <span className="flex items-center gap-2 text-sm text-gray-700">
                    {p.connected && p.verified ? (
                      <Check className="h-4 w-4 text-green-500 shrink-0" />
                    ) : (
                      <Circle className="h-4 w-4 text-gray-300 shrink-0" />
                    )}
                    {p.label}
                  </span>
                  <span className="text-xs text-gray-400">
                    {p.connected && p.verified ? "Verified" : p.connected ? "Not tested yet" : "Not connected"}
                  </span>
                </button>
              ))
            )}
          </div>

          <button
            type="button"
            onClick={props.onChangeMode}
            className="w-full flex items-center justify-between gap-2 rounded-lg border border-gray-100 px-3 py-2 hover:border-blue-200 transition-colors text-left"
          >
            <span className="flex items-center gap-2 text-sm text-gray-700">
              <Check className="h-4 w-4 text-green-500 shrink-0" />
              Publish mode
            </span>
            <span className="text-xs text-gray-400">{MODE_LABEL[props.publishMode]}</span>
          </button>

          <div className="flex items-center gap-2 rounded-lg border border-gray-100 px-3 py-2">
            {props.hasContentReady ? (
              <Check className="h-4 w-4 text-green-500 shrink-0" />
            ) : (
              <Circle className="h-4 w-4 text-gray-300 shrink-0" />
            )}
            <span className="text-sm text-gray-700">Get a first piece of content ready</span>
            {!props.hasContentReady && (
              <span className="text-xs text-gray-400 ml-auto">Stage an idea on your Dashboard</span>
            )}
          </div>

          <div className="flex items-center gap-2 rounded-lg border border-gray-100 px-3 py-2">
            {props.hasConfirmedPost ? (
              <Check className="h-4 w-4 text-green-500 shrink-0" />
            ) : (
              <Circle className="h-4 w-4 text-gray-300 shrink-0" />
            )}
            <span className="text-sm text-gray-700">Confirm your first real post</span>
            {!props.hasConfirmedPost && (
              <span className="text-xs text-gray-400 ml-auto flex items-center gap-1">
                <Link2 className="h-3 w-3" /> Paste the link once you've posted
              </span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

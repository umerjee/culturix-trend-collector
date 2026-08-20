"use client";

import { useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { EXPRESSION_NAMES, type Expression } from "@/lib/types";
import ImageUploadButton from "@/components/ImageUploadButton";

interface Props {
  brandId: string;
  variantId: string;
  // Required for AI generation — the backend grounds each expression on
  // this variant's own portrait, so there's nothing to generate from until
  // one exists.
  hasPortrait: boolean;
  // Bulk generation is backgrounded server-side (see CharacterVariant.
  // expressions_generating's docstring — a synchronous version got killed
  // mid-batch by Vercel's own serverless function limit, independent of
  // any client-side timeout). The parent owns starting it and polling the
  // variant, matching how it already owns registerElement/trainLora — this
  // component just reflects that state and refetches its own expression
  // list while a batch is in flight.
  generatingAll: boolean;
  generateAllErrors: Record<string, string>;
  onGenerateAll: () => void;
  startingGenerateAll: boolean;
  generateAllStartError: string | null;
}

export default function ExpressionUploadGrid({
  brandId, variantId, hasPortrait,
  generatingAll, generateAllErrors, onGenerateAll, startingGenerateAll, generateAllStartError,
}: Props) {
  const [expressions, setExpressions] = useState<Expression[] | null>(null);
  const [generatingName, setGeneratingName] = useState<string | null>(null);
  const [genError, setGenError] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    setExpressions(null);
    fetch(`/api/culturetoons/variants/${variantId}/expressions?brand_id=${brandId}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => { if (!cancelled) setExpressions(Array.isArray(data) ? data : []); });
    return () => { cancelled = true; };
  }, [variantId, brandId]);

  // Refetches while a bulk batch is running (so images fill in live as
  // each one lands), plus once more on the transition to done, so the
  // very last completed image isn't missed between poll ticks.
  useEffect(() => {
    let cancelled = false;
    const refetch = () => {
      fetch(`/api/culturetoons/variants/${variantId}/expressions?brand_id=${brandId}`, { cache: "no-store" })
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => { if (!cancelled && Array.isArray(data)) setExpressions(data); });
    };
    refetch();
    if (!generatingAll) {
      if (generateAllErrors && Object.keys(generateAllErrors).length > 0) {
        setGenError((prev) => ({ ...prev, ...generateAllErrors }));
      }
      return () => { cancelled = true; };
    }
    const interval = setInterval(refetch, 4000);
    return () => { cancelled = true; clearInterval(interval); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generatingAll, variantId, brandId]);

  if (expressions === null) {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-400 py-4">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading expressions…
      </div>
    );
  }

  function byName(name: string) {
    return expressions?.find((e) => e.name === name) ?? null;
  }

  async function generate(name: string) {
    setGeneratingName(name);
    setGenError((prev) => ({ ...prev, [name]: "" }));
    try {
      const res = await fetch(`/api/culturetoons/variants/${variantId}/expressions/${encodeURIComponent(name)}/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setGenError((prev) => ({ ...prev, [name]: typeof data.detail === "string" ? data.detail : "Generation failed" }));
        return;
      }
      setExpressions((prev) => {
        const row = data as Expression;
        const rest = (prev ?? []).filter((e) => e.name !== name);
        return [...rest, row];
      });
    } finally {
      setGeneratingName(null);
    }
  }

  const missingCount = EXPRESSION_NAMES.filter((name) => !byName(name)?.image_url).length;
  const busyWithAll = startingGenerateAll || generatingAll;

  return (
    <div>
      {!hasPortrait && (
        <p className="text-[11px] text-gray-400 mb-2">Build this variant&apos;s own portrait above to unlock AI-generated expressions.</p>
      )}
      {hasPortrait && missingCount > 0 && (
        <div className="flex items-center gap-2 mb-3">
          <button
            type="button"
            onClick={onGenerateAll}
            disabled={busyWithAll || generatingName !== null}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
          >
            {busyWithAll ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            {generatingAll
              ? `Generating ${missingCount} expression${missingCount === 1 ? "" : "s"}…`
              : startingGenerateAll
                ? "Starting…"
                : `Generate all ${missingCount} missing expression${missingCount === 1 ? "" : "s"}`}
          </button>
        </div>
      )}
      {generateAllStartError && <p className="text-[11px] text-red-500 mb-2">{generateAllStartError}</p>}
      <div className="grid grid-cols-5 gap-3">
        {EXPRESSION_NAMES.map((name) => {
          const existing = byName(name);
          const generating = generatingName === name;
          return (
            <div key={name} className="flex flex-col items-center gap-1">
              <ImageUploadButton
                size="sm"
                label={name}
                uploadUrl={`/api/culturetoons/variants/${variantId}/expressions/${encodeURIComponent(name)}/image`}
                currentImageUrl={existing?.image_url ?? null}
                extraFields={{ brand_id: brandId }}
                onUploaded={(data) => {
                  setExpressions((prev) => {
                    const row = data as unknown as Expression;
                    const rest = (prev ?? []).filter((e) => e.name !== name);
                    return [...rest, row];
                  });
                }}
              />
              <button
                type="button"
                onClick={() => generate(name)}
                disabled={!hasPortrait || generating || busyWithAll}
                title={hasPortrait ? "Generate this expression with AI, from your portrait" : "Build a portrait first"}
                className="inline-flex items-center gap-1 text-[10px] text-blue-500 hover:text-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {generating ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <Sparkles className="h-2.5 w-2.5" />}
                {existing ? "Regenerate" : "Generate"}
              </button>
              {genError[name] && <span className="text-[9px] text-red-500 text-center max-w-[4.5rem]">{genError[name]}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

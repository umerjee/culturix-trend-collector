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
}

export default function ExpressionUploadGrid({ brandId, variantId, hasPortrait }: Props) {
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

  return (
    <div>
      {!hasPortrait && (
        <p className="text-[11px] text-gray-400 mb-2">Build this variant&apos;s own portrait above to unlock AI-generated expressions.</p>
      )}
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
                disabled={!hasPortrait || generating}
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

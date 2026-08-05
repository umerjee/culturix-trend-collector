"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { EXPRESSION_NAMES, type Expression } from "@/lib/types";
import ImageUploadButton from "@/components/ImageUploadButton";

interface Props {
  brandId: string;
  variantId: string;
}

export default function ExpressionUploadGrid({ brandId, variantId }: Props) {
  const [expressions, setExpressions] = useState<Expression[] | null>(null);

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

  return (
    <div className="grid grid-cols-5 gap-3">
      {EXPRESSION_NAMES.map((name) => {
        const existing = byName(name);
        return (
          <ImageUploadButton
            key={name}
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
        );
      })}
    </div>
  );
}

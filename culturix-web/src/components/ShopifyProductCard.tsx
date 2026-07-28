"use client";

import { useState } from "react";
import { Wand2, Loader2, AlertCircle, ExternalLink, RefreshCw } from "lucide-react";
import type { ShopifyProduct } from "@/lib/types";

interface Props {
  product: ShopifyProduct;
}

const PLATFORM_COLORS: Record<string, string> = {
  Instagram: "bg-purple-50 text-purple-600",
  TikTok: "bg-pink-50 text-pink-600",
  Pinterest: "bg-red-50 text-red-600",
};

export default function ShopifyProductCard({ product }: Props) {
  const [idea, setIdea] = useState(product.idea);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    if (generating) return;
    setGenerating(true);
    setError(null);
    try {
      const res = await fetch(`/api/shopify/products/${product.id}/generate-idea`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? `Error ${res.status}`);
        return;
      }
      setIdea(data.idea);
    } catch {
      setError("Network error — check your connection");
    } finally {
      setGenerating(false);
    }
  }

  const image = product.image_urls[0];

  return (
    <div className="rounded-2xl bg-white border border-gray-100 overflow-hidden flex flex-col">
      <div className="aspect-square bg-gray-50 relative">
        {image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={image} alt={product.title} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-xs text-gray-300">No photo</div>
        )}
      </div>

      <div className="p-4 flex flex-col gap-2 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p className="font-semibold text-sm text-gray-900 line-clamp-2">{product.title}</p>
          {product.product_url && (
            <a
              href={product.product_url}
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 text-gray-300 hover:text-gray-500"
              title="View on Shopify"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
        {product.price && (
          <p className="text-xs text-gray-400">
            {product.price} {product.currency}
          </p>
        )}

        {idea ? (
          <div className="mt-1 pt-3 border-t border-gray-50 space-y-2">
            <div className="flex items-center justify-between gap-2">
              {idea.platform && (
                <span className={`inline-flex items-center text-xs font-medium rounded-full px-2 py-0.5 ${PLATFORM_COLORS[idea.platform] ?? "bg-gray-100 text-gray-600"}`}>
                  {idea.platform}
                </span>
              )}
              <button
                onClick={generate}
                disabled={generating}
                title="Regenerate idea"
                className="text-gray-300 hover:text-blue-500 disabled:opacity-50"
              >
                {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              </button>
            </div>
            <p className="text-sm font-medium text-gray-900">{idea.hook}</p>
            <p className="text-xs text-gray-500 line-clamp-4">{idea.caption}</p>
            {idea.hashtag_strategy && (
              <p className="text-xs text-blue-500">{idea.hashtag_strategy}</p>
            )}
            {idea.cta && <p className="text-xs text-gray-400 italic">{idea.cta}</p>}
            {error && (
              <p className="flex items-start gap-1.5 text-xs text-red-500">
                <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                {error}
              </p>
            )}
          </div>
        ) : (
          <div className="mt-auto pt-3 border-t border-gray-50 space-y-2">
            <button
              onClick={generate}
              disabled={generating}
              className="w-full flex items-center justify-center gap-1.5 rounded-lg border border-gray-200 py-2 text-xs font-medium text-gray-500 hover:border-blue-300 hover:text-blue-600 transition-colors disabled:opacity-60"
            >
              {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
              {generating ? "Generating…" : "Generate post idea"}
            </button>
            {error && (
              <p className="flex items-start gap-1.5 text-xs text-red-500">
                <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                {error}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

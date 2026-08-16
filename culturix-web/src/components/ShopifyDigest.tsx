"use client";

import { useEffect, useState } from "react";
import { RefreshCw, Loader2, Wand2, CheckCircle, XCircle, Clock } from "lucide-react";
import type { ShopifyStore, ShopifyProduct } from "@/lib/types";
import ShopifyProductCard from "@/components/ShopifyProductCard";
import ProductSetupStatus, { type SetupStep } from "@/components/onboarding/ProductSetupStatus";

type SetupAction = "sync" | "generate";

interface Props {
  initialStore: ShopifyStore;
  initialProducts: ShopifyProduct[];
}

function fmt(iso: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function ShopifyDigest({ initialStore, initialProducts }: Props) {
  const [store, setStore] = useState(initialStore);
  const [products, setProducts] = useState(initialProducts);
  const [syncing, setSyncing] = useState(false);
  const [generatingBulk, setGeneratingBulk] = useState(false);
  const [bulkMessage, setBulkMessage] = useState<string | null>(null);
  const hasIdea = products.some((p) => !!p.idea);
  const hasReel = products.some((p) => p.reel?.status === "done");
  const [setupCollapsed, setSetupCollapsed] = useState(() => products.length > 0 && hasIdea && hasReel);

  // Poll while a sync is actively running so status/product count update
  // without the user having to manually refresh the page.
  useEffect(() => {
    if (store.last_sync_status !== "running") return;
    const interval = setInterval(async () => {
      const res = await fetch("/api/shopify/store", { cache: "no-store" });
      if (res.ok) setStore(await res.json());
    }, 4000);
    return () => clearInterval(interval);
  }, [store.last_sync_status]);

  async function refreshProducts() {
    const res = await fetch("/api/shopify/products", { cache: "no-store" });
    if (res.ok) setProducts(await res.json());
  }

  async function triggerSync() {
    setSyncing(true);
    try {
      await fetch("/api/shopify/sync", { method: "POST" });
      const res = await fetch("/api/shopify/store", { cache: "no-store" });
      if (res.ok) setStore(await res.json());
    } finally {
      setSyncing(false);
    }
  }

  async function generateBulk() {
    setGeneratingBulk(true);
    setBulkMessage(null);
    try {
      await fetch("/api/shopify/generate-ideas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 10 }),
      });
      setBulkMessage("Generating ideas for up to 10 products without one — this runs in the background, check back shortly and refresh.");
    } finally {
      setGeneratingBulk(false);
    }
  }

  const missingIdeaCount = products.filter((p) => !p.idea).length;

  const setupSteps: SetupStep<SetupAction>[] = [
    {
      label: "Sync your catalog", action: "sync",
      hint: "Pull in your recent products — titles, prices, and photos.",
      done: products.length > 0,
    },
    {
      label: "Generate a post idea", action: "generate",
      hint: "AI writes a hook, caption, and hashtag strategy from a product's real details.",
      done: hasIdea,
    },
    {
      label: "Generate a reel", action: "generate",
      hint: "Turn a product's real photo into a short-form AI video.",
      done: hasReel,
    },
  ];

  function handleSetupNavigate(action: SetupAction) {
    if (action === "sync") triggerSync();
    else generateBulk();
  }

  return (
    <div className="space-y-6">
      <ProductSetupStatus
        title="Getting started"
        steps={setupSteps}
        collapsed={setupCollapsed}
        onToggleCollapsed={() => setSetupCollapsed((c) => !c)}
        onNavigate={handleSetupNavigate}
      />

      <div className="rounded-2xl bg-white border border-gray-100 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-semibold text-gray-900">{store.shop_name || store.shop_domain}</h2>
            <p className="text-xs text-gray-400 mt-0.5">{store.shop_domain}</p>
          </div>
          <div className="flex items-center gap-2">
            {store.last_sync_status === "running" ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-amber-600 bg-amber-50 rounded-full px-3 py-1.5">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Syncing…
              </span>
            ) : store.last_sync_status === "error" ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-red-600 bg-red-50 rounded-full px-3 py-1.5" title={store.last_sync_error ?? undefined}>
                <XCircle className="h-3.5 w-3.5" /> Last sync failed
              </span>
            ) : store.last_sync_status === "ok" ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-600 bg-emerald-50 rounded-full px-3 py-1.5">
                <CheckCircle className="h-3.5 w-3.5" /> Synced
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-400 bg-gray-50 rounded-full px-3 py-1.5">
                <Clock className="h-3.5 w-3.5" /> Not synced yet
              </span>
            )}
            <button
              onClick={triggerSync}
              disabled={syncing || store.last_sync_status === "running"}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:border-primary-300 hover:text-primary-600 transition-colors disabled:opacity-50"
            >
              {syncing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Sync now
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-x-6 gap-y-1 mt-4 text-xs text-gray-400">
          <span>{store.product_count} products (last 90 days)</span>
          <span>Last synced {fmt(store.last_synced_at)}</span>
        </div>
      </div>

      {products.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-gray-500">
            {products.length} product{products.length !== 1 ? "s" : ""} in your digest
            {missingIdeaCount > 0 && ` — ${missingIdeaCount} without a post idea yet`}
          </p>
          {missingIdeaCount > 0 && (
            <div className="flex items-center gap-2">
              <button
                onClick={generateBulk}
                disabled={generatingBulk}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 text-white text-xs font-medium px-3 py-2 hover:bg-primary-700 transition-colors disabled:opacity-60"
              >
                {generatingBulk ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
                Generate ideas for next 10
              </button>
              <button
                onClick={refreshProducts}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                Refresh
              </button>
            </div>
          )}
        </div>
      )}
      {bulkMessage && <p className="text-xs text-primary-500">{bulkMessage}</p>}

      {products.length === 0 ? (
        <div className="rounded-2xl border-2 border-dashed border-gray-200 py-16 text-center">
          <p className="text-sm text-gray-400">
            {store.last_sync_status === "running"
              ? "Your catalog is syncing — products will appear here shortly."
              : "No products synced yet. Click “Sync now” above to pull in your catalog."}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
          {products.map((p) => (
            <ShopifyProductCard key={p.id} product={p} />
          ))}
        </div>
      )}
    </div>
  );
}

"use client";

import { useState } from "react";
import { ShoppingBag } from "lucide-react";

export default function ShopifyConnectForm() {
  const [shopDomain, setShopDomain] = useState("");

  function connect(e: React.FormEvent) {
    e.preventDefault();
    if (!shopDomain.trim()) return;
    window.location.href = `/api/shopify/connect?shop_domain=${encodeURIComponent(shopDomain.trim())}`;
  }

  return (
    <div className="rounded-2xl border-2 border-dashed border-gray-200 py-16 px-6 text-center">
      <ShoppingBag className="h-10 w-10 text-gray-300 mx-auto mb-4" />
      <h3 className="font-semibold text-gray-700 mb-2">Connect your Shopify store</h3>
      <p className="text-sm text-gray-400 max-w-sm mx-auto mb-5">
        Link your store to pull in your product catalog and get daily post ideas built from your
        real product photos.
      </p>
      <form onSubmit={connect} className="flex flex-col sm:flex-row gap-2 max-w-sm mx-auto">
        <input
          type="text"
          value={shopDomain}
          onChange={(e) => setShopDomain(e.target.value)}
          placeholder="your-store.myshopify.com"
          className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        <button
          type="submit"
          className="rounded-lg bg-blue-600 text-white text-sm font-medium px-4 py-2 hover:bg-blue-700 transition-colors shrink-0"
        >
          Connect
        </button>
      </form>
    </div>
  );
}

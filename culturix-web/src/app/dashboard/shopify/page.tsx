import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import AppNav from "@/components/AppNav";
import ShopifyConnectForm from "@/components/ShopifyConnectForm";
import ShopifyDigest from "@/components/ShopifyDigest";
import type { ShopifyStore, ShopifyProduct } from "@/lib/types";

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

async function fetchStore(userId: string): Promise<ShopifyStore | null> {
  try {
    const res = await fetch(`${RAILWAY}/api/shopify/store?user_id=${userId}`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function fetchProducts(userId: string): Promise<ShopifyProduct[]> {
  try {
    const res = await fetch(`${RAILWAY}/api/shopify/products?user_id=${userId}`, { cache: "no-store" });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export default async function ShopifyPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

  const isSuperAdmin = user.email === "umer.ali79@gmail.com";
  const store = await fetchStore(user.id);
  const products = store ? await fetchProducts(user.id) : [];

  return (
    <div className="min-h-screen bg-gray-50">
      <AppNav active="shopify" isSuperAdmin={isSuperAdmin} product="shopify" />

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Shopify</h1>
          <p className="text-sm text-gray-500 mt-1">
            Daily post ideas built from your real product photos.
          </p>
        </div>

        {store ? (
          <ShopifyDigest initialStore={store} initialProducts={products} />
        ) : (
          <ShopifyConnectForm />
        )}
      </main>
    </div>
  );
}

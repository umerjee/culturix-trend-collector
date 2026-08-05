import Link from "next/link";
import {
  Zap, ArrowRight, ShoppingBag, Link2, RefreshCw, Sparkles, Clapperboard, ImageIcon,
} from "lucide-react";

export const metadata = {
  title: "Shopify Reel Building — Culturix",
  description:
    "Connect your Shopify store and get AI-generated post ideas and short-form video reels built from your real product photos — no stock footage, no generic AI visuals.",
};

const FEATURES = [
  {
    icon: Link2,
    title: "One-click store connection",
    desc: "Connect via Shopify's own OAuth flow. Culturix never sees or asks for your store password.",
  },
  {
    icon: RefreshCw,
    title: "Automatic catalog sync",
    desc: "We pull in your recent product catalog — titles, descriptions, prices, and photos — ready to turn into content.",
  },
  {
    icon: Sparkles,
    title: "AI post ideas per product",
    desc: "Hook, caption, CTA, and hashtag strategy generated from each product's real details, not a generic template.",
  },
  {
    icon: Clapperboard,
    title: "Reels from your real photos",
    desc: "AI image-to-video animates your product's actual uploaded photo into a short-form video — grounded in what you actually sell.",
  },
];

const STEPS = [
  { num: "01", title: "Connect your store", desc: "Authorize Culturix through Shopify's standard OAuth flow — takes under a minute." },
  { num: "02", title: "We sync your catalog", desc: "Your recent products come in automatically, photos and all, ready in your dashboard." },
  { num: "03", title: "Generate ideas & reels", desc: "Pick a product, generate a post idea or a full video reel on demand, and review the result." },
  { num: "04", title: "Post it", desc: "Take the finished idea or reel to your own Shopify social channels, on your terms." },
];

export default function ShopifyProductPage() {
  return (
    <div className="min-h-screen bg-white">
      <header className="bg-white border-b border-gray-100 sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-blue-600" />
            <span className="font-bold text-lg tracking-tight">Culturix</span>
          </Link>
          <Link href="/signup" className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors font-medium">
            Get started free
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-14">
        <div className="text-center mb-14">
          <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-600 text-xs font-semibold px-3 py-1.5 mb-6">
            <ShoppingBag className="h-3.5 w-3.5" />
            Now piloting
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 mb-4">
            Shopify Reel Building
          </h1>
          <p className="text-gray-500 max-w-xl mx-auto leading-relaxed">
            Your product catalog is already your best content library. Connect your Shopify store and
            Culturix turns your real products — real photos, real prices, real descriptions — into
            post ideas and short-form video reels, ready to publish.
          </p>
        </div>

        {/* Features */}
        <section className="mb-16 grid sm:grid-cols-2 gap-6">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-2xl border border-gray-100 p-6">
              <div className="h-10 w-10 rounded-xl bg-emerald-50 flex items-center justify-center mb-4">
                <f.icon className="h-5 w-5 text-emerald-500" />
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">{f.title}</h3>
              <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </section>

        {/* How it works */}
        <section className="mb-16">
          <h2 className="text-lg font-semibold text-gray-900 mb-8 text-center">How it works</h2>
          <div className="grid sm:grid-cols-2 gap-8">
            {STEPS.map((s) => (
              <div key={s.num} className="flex gap-4">
                <div className="shrink-0 inline-flex items-center justify-center h-10 w-10 rounded-full bg-emerald-50 text-emerald-600 font-bold text-sm">
                  {s.num}
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900 mb-1">{s.title}</h3>
                  <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Why real photos matter */}
        <section className="mb-16 rounded-2xl bg-gray-50 border border-gray-100 p-6 sm:p-8 flex items-start gap-4">
          <ImageIcon className="h-5 w-5 text-emerald-500 mt-0.5 shrink-0" />
          <p className="text-sm text-gray-600 leading-relaxed">
            Generic AI product videos look generic. Every reel Culturix builds for your Shopify
            catalog is animated directly from the photo you actually uploaded to your store — so what
            gets posted still looks unmistakably like <em>your</em> product.
          </p>
        </section>

        {/* CTA */}
        <section className="text-center">
          <Link
            href="/signup"
            className="inline-flex items-center gap-2 bg-blue-600 text-white font-semibold px-8 py-4 rounded-xl hover:bg-blue-700 transition-colors"
          >
            Connect your store <ArrowRight className="h-4 w-4" />
          </Link>
          <p className="text-xs text-gray-400 mt-4">
            Also want trend-driven content ideas or AI cartoon characters?{" "}
            <Link href="/#products" className="text-blue-600 hover:underline">See all Culturix products</Link>
          </p>
        </section>
      </main>
    </div>
  );
}

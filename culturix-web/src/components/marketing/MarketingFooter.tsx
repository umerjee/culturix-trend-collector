import Link from "next/link";
import { Zap } from "lucide-react";

export default function MarketingFooter() {
  return (
    <footer className="py-8 px-4 sm:px-6 border-t border-white/5 bg-slate-950">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-sm">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-primary-400" />
          <span className="font-semibold text-gray-300">Culturix</span>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-4">
          <Link href="/products/posting-ideation" className="text-gray-500 hover:text-gray-300 transition-colors">Posting Ideation</Link>
          <Link href="/products/shopify" className="text-gray-500 hover:text-gray-300 transition-colors">Shopify Reel Building</Link>
          <Link href="/products/culturetoons" className="text-gray-500 hover:text-gray-300 transition-colors">Character-Based Posting</Link>
          <Link href="/how-it-works" className="text-gray-500 hover:text-gray-300 transition-colors">How Publishing Works</Link>
          <Link href="/privacy" className="text-gray-500 hover:text-gray-300 transition-colors">Privacy Policy</Link>
          <Link href="/terms" className="text-gray-500 hover:text-gray-300 transition-colors">Terms of Service</Link>
        </div>
        <p className="text-gray-600">© 2026 Culturix. All rights reserved.</p>
      </div>
    </footer>
  );
}

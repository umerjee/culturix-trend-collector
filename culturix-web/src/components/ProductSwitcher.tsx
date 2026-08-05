"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { ChevronDown, Lightbulb, ShoppingBag, Drama, Check } from "lucide-react";

export type ProductKey = "posting-ideation" | "shopify" | "culturetoons";

interface ProductInfo {
  key: ProductKey;
  href: string;
  label: string;
  description: string;
  icon: React.ReactNode;
}

const PRODUCTS: ProductInfo[] = [
  {
    key: "posting-ideation",
    href: "/dashboard",
    label: "Posting Ideation",
    description: "Trend-driven content ideas & publishing",
    icon: <Lightbulb className="h-4 w-4" />,
  },
  {
    key: "shopify",
    href: "/dashboard/shopify",
    label: "Shopify Reel Building",
    description: "AI reels grounded in your real product catalog",
    icon: <ShoppingBag className="h-4 w-4" />,
  },
  {
    key: "culturetoons",
    href: "/dashboard/culturetoons",
    label: "Character-Based Posting",
    description: "Cartoon characters riffing on cultural trends",
    icon: <Drama className="h-4 w-4" />,
  },
];

interface Props {
  product: ProductKey;
}

export default function ProductSwitcher({ product }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = PRODUCTS.find((p) => p.key === product) ?? PRODUCTS[0];

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 text-sm font-medium rounded-lg px-2 sm:px-3 py-2 text-gray-700 hover:bg-gray-50 border border-gray-200 transition-colors"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {current.icon}
        <span className="hidden md:inline">{current.label}</span>
        <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full mt-1 w-72 bg-white border border-gray-100 rounded-xl shadow-lg py-1.5 z-20"
        >
          <div className="px-3 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide">
            Culturix products
          </div>
          {PRODUCTS.map((p) => (
            <Link
              key={p.key}
              href={p.href}
              onClick={() => setOpen(false)}
              className={`flex items-start gap-2.5 px-3 py-2 transition-colors ${
                p.key === product ? "bg-blue-50" : "hover:bg-gray-50"
              }`}
            >
              <span className={`mt-0.5 ${p.key === product ? "text-blue-600" : "text-gray-400"}`}>{p.icon}</span>
              <span className="flex-1 min-w-0">
                <span className={`block text-sm font-medium ${p.key === product ? "text-blue-600" : "text-gray-900"}`}>
                  {p.label}
                </span>
                <span className="block text-xs text-gray-500">{p.description}</span>
              </span>
              {p.key === product && <Check className="h-4 w-4 text-blue-600 mt-0.5" />}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

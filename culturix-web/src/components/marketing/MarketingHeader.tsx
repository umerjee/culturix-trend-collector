import Link from "next/link";
import { Zap } from "lucide-react";
import { buttonVariants } from "@/components/ui/Button";
import MobileMenu, { type NavLink } from "./MobileMenu";

interface Props {
  // Home page only — dark, fixed-over-hero nav. Every other marketing/auth
  // page uses the default light sticky header.
  transparent?: boolean;
  // Replaces the default "Get started free" CTA (e.g. legal pages cross-link
  // to each other instead).
  rightSlot?: React.ReactNode;
  // Auth pages omit the CTA — linking back to /signup from the signup page
  // itself is a no-op.
  showCta?: boolean;
}

const LINKS: NavLink[] = [
  { href: "/world", label: "Explore the map" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#creators", label: "For creators" },
  { href: "/#pricing", label: "Pricing" },
];

export default function MarketingHeader({ transparent, rightSlot, showCta = true }: Props) {
  if (transparent) {
    return (
      <nav className="fixed top-0 left-0 right-0 z-50 bg-slate-950/90 backdrop-blur-sm border-b border-white/10">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-3">
          <Link href="/" className="flex items-center gap-2 shrink-0">
            <Zap className="h-5 w-5 text-primary-400" />
            <span className="font-bold text-lg tracking-tight text-white">Culturix</span>
          </Link>
          <div className="hidden md:flex items-center gap-1">
            {LINKS.map((l) => (
              <Link key={l.href} href={l.href} className="text-sm text-gray-400 hover:text-white px-3 py-1.5 transition-colors whitespace-nowrap">
                {l.label}
              </Link>
            ))}
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <Link href="/signup" className="hidden md:inline text-sm text-gray-400 hover:text-white px-3 py-1.5 transition-colors">
              Sign in
            </Link>
            <Link href="/signup" className={`hidden sm:inline-flex ${buttonVariants({ variant: "primary", size: "sm" })}`}>
              Get started free
            </Link>
            <MobileMenu dark links={[...LINKS, { href: "/signup", label: "Sign in" }]} ctaHref="/signup" ctaLabel="Get started free" />
          </div>
        </div>
      </nav>
    );
  }

  return (
    <header className="bg-white border-b border-gray-100 sticky top-0 z-30">
      <div className="relative max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-3">
        <Link href="/" className="flex items-center gap-2 shrink-0">
          <Zap className="h-5 w-5 text-primary-600" />
          <span className="font-bold text-lg tracking-tight">Culturix</span>
        </Link>
        <div className="hidden md:flex items-center gap-1">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="text-sm text-gray-500 hover:text-primary-600 px-3 py-1.5 transition-colors whitespace-nowrap">
              {l.label}
            </Link>
          ))}
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          {rightSlot ?? (showCta && (
            <Link href="/signup" className={`hidden sm:inline-flex ${buttonVariants({ variant: "primary", size: "sm" })}`}>
              Get started free
            </Link>
          ))}
          <MobileMenu links={LINKS} ctaHref="/signup" ctaLabel="Get started free" hideCta={!showCta || !!rightSlot} />
        </div>
      </div>
    </header>
  );
}

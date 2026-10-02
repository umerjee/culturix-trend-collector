import Link from "next/link";
import { Suspense } from "react";
import { Zap } from "lucide-react";
import { buttonVariants } from "@/components/ui/Button";
import NavText from "@/components/i18n/NavText";
import MobileMenu, { type NavLink } from "./MobileMenu";
import LanguageSwitcher from "./LanguageSwitcher";

interface Props {
  // Home page only — dark, fixed-over-hero nav. Every other marketing/auth
  // page uses the default light sticky header.
  transparent?: boolean;
  // Replaces the default "Start watching" CTA (e.g. legal pages cross-link
  // to each other instead).
  rightSlot?: React.ReactNode;
  // Pages that are already the destination (/world, a video) or auth pages omit the CTA.
  showCta?: boolean;
}

// Viewer-only public site: every link leads to watching or understanding the videos. Creator
// products, pricing and sign-up do not belong here (see CLAUDE.md, /world redesign note).
const LINKS: NavLink[] = [
  { href: "/world", labelKey: "watch" },
  { href: "/#how-it-works", labelKey: "howItWorks" },
  { href: "/#faq", labelKey: "faq" },
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
                <NavText k={l.labelKey} />
              </Link>
            ))}
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <Suspense fallback={null}><LanguageSwitcher /></Suspense>
            <Link href="/world" className={`hidden sm:inline-flex ${buttonVariants({ variant: "primary", size: "sm" })}`}>
              <NavText k="startWatching" />
            </Link>
            <MobileMenu dark links={LINKS} ctaHref="/world" ctaLabelKey="startWatching" />
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
              <NavText k={l.labelKey} />
            </Link>
          ))}
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          <Suspense fallback={null}><LanguageSwitcher /></Suspense>
          {rightSlot ?? (showCta && (
            <Link href="/world" className={`hidden sm:inline-flex ${buttonVariants({ variant: "primary", size: "sm" })}`}>
              <NavText k="startWatching" />
            </Link>
          ))}
          <MobileMenu links={LINKS} ctaHref="/world" ctaLabelKey="startWatching" hideCta={!showCta || !!rightSlot} />
        </div>
      </div>
    </header>
  );
}

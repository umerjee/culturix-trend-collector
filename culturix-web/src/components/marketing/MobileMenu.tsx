"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";

export interface NavLink {
  href: string;
  label: string;
}

// Below md the header links collapse into this menu. Without it, phone
// visitors could not reach /world from the nav at all.
export default function MobileMenu({ links, dark, ctaHref, ctaLabel, hideCta }: {
  links: NavLink[];
  dark?: boolean;
  ctaHref: string;
  ctaLabel: string;
  hideCta?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => { setOpen(false); }, [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const linkClass = dark
    ? "text-gray-200 hover:bg-white/5"
    : "text-gray-700 hover:bg-gray-50";

  return (
    <div className="md:hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        className={`-mr-2 flex h-11 w-11 items-center justify-center rounded-lg ${dark ? "text-gray-300 hover:bg-white/5" : "text-gray-600 hover:bg-gray-50"}`}
      >
        {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {open && (
        <div className={`absolute left-0 right-0 top-16 border-b shadow-lg ${dark ? "bg-slate-950 border-white/10" : "bg-white border-gray-100"}`}>
          <nav className="mx-auto flex max-w-6xl flex-col px-4 py-3 sm:px-6" aria-label="Main">
            {links.map((l) => (
              <Link key={l.href} href={l.href} onClick={() => setOpen(false)} className={`flex min-h-12 items-center rounded-lg px-3 text-base font-medium ${linkClass}`}>
                {l.label}
              </Link>
            ))}
            {!hideCta && <Link
              href={ctaHref}
              onClick={() => setOpen(false)}
              className="mt-2 flex min-h-12 items-center justify-center rounded-xl bg-primary-600 px-4 text-base font-semibold text-white hover:bg-primary-700"
            >
              {ctaLabel}
            </Link>}
          </nav>
        </div>
      )}
    </div>
  );
}

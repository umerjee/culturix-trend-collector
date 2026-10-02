"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Zap, LayoutDashboard, TrendingUp, Layers, Users, Search, LogOut, History, ShieldCheck, Database, Film, Laugh, Clapperboard, Newspaper, X } from "lucide-react";

const NAV: { href: string; icon: React.ReactNode; label: string; group: string }[] = [
  { href: "/admin/overview", icon: <LayoutDashboard className="h-4 w-4" />, label: "Overview", group: "Workspace" },
  { href: "/admin/trends", icon: <TrendingUp className="h-4 w-4" />, label: "Trends", group: "Intelligence" },
  { href: "/admin/clusters", icon: <Layers className="h-4 w-4" />, label: "Clusters", group: "Intelligence" },
  { href: "/admin/personas", icon: <Users className="h-4 w-4" />, label: "Personas", group: "Intelligence" },
  { href: "/admin/history", icon: <History className="h-4 w-4" />, label: "History", group: "Intelligence" },
  { href: "/admin/validation", icon: <ShieldCheck className="h-4 w-4" />, label: "Validation", group: "Operations" },
  { href: "/admin/curated-items", icon: <Database className="h-4 w-4" />, label: "Source library", group: "Production" },
  { href: "/admin/world-production", icon: <Film className="h-4 w-4" />, label: "World production", group: "Production" },
  { href: "/admin/editorial", icon: <Newspaper className="h-4 w-4" />, label: "Trend editorial", group: "Production" },
  { href: "/admin/comedy-videos", icon: <Clapperboard className="h-4 w-4" />, label: "Comedy studio", group: "Production" },
  { href: "/admin/comedy-patterns", icon: <Laugh className="h-4 w-4" />, label: "Comedy patterns", group: "Production" },
  { href: "/admin/users", icon: <Users className="h-4 w-4" />, label: "Users", group: "Administration" },
  { href: "/admin/search", icon: <Search className="h-4 w-4" />, label: "Search", group: "Administration" },
];

interface Props {
  pendingCount: number;
  className?: string;
  // Drawer mode (phones / iPad portrait): larger touch targets, a close
  // button, and navigation closes the drawer.
  mobile?: boolean;
  onNavigate?: () => void;
  onClose?: () => void;
}

// Switching sections is real Next.js navigation (bookmarkable URLs, working
// browser back/forward). The shell (AdminShell) owns the drawer state and the
// pending-users fetch so the desktop column and the mobile drawer share both.
export default function AdminSidebar({ pendingCount, className = "", mobile, onNavigate, onClose }: Props) {
  const pathname = usePathname();

  return (
    <aside className={`bg-white flex flex-col ${className}`}>
      <div className="h-16 flex items-center justify-between gap-2 px-5 border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2">
          <Zap className="h-5 w-5 text-primary-600" />
          <span className="font-bold text-base tracking-tight text-gray-900">Culturix</span>
        </div>
        {mobile && (
          <button type="button" onClick={onClose} aria-label="Close menu" className="-mr-2 flex h-11 w-11 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-50">
            <X className="h-5 w-5" />
          </button>
        )}
      </div>

      <nav className="flex-1 py-4 space-y-0.5 px-2 overflow-y-auto" aria-label="Admin sections">
        {NAV.map(({ href, icon, label, group }, index) => {
          const active = pathname === href || (href !== "/admin/overview" && pathname?.startsWith(href));
          return (
            <div key={href}>
              {(index === 0 || NAV[index - 1].group !== group) && (
                <p className="mb-1 mt-4 px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-gray-400 first:mt-0">{group}</p>
              )}
              <Link
                href={href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={`w-full flex items-center gap-3 px-3 rounded-lg text-sm font-medium transition-colors text-left ${
                  mobile ? "py-3" : "py-2"
                } ${active ? "bg-primary-50 text-primary-600" : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"}`}
              >
                {icon}
                {label}
                {href === "/admin/users" && pendingCount > 0 && (
                  <span className="ml-auto text-xs font-semibold text-amber-600">{pendingCount}</span>
                )}
              </Link>
            </div>
          );
        })}
      </nav>

      <div className="p-3 border-t border-gray-100 shrink-0">
        <a
          href="/dashboard"
          className={`flex items-center gap-2 px-3 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors ${
            mobile ? "py-3 text-sm" : "py-2 text-xs"
          }`}
        >
          <LogOut className="h-3.5 w-3.5" />
          Back to app
        </a>
      </div>
    </aside>
  );
}

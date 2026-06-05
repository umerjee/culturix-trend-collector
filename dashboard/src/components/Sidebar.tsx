"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, TrendingUp, Network, Users, Search, Zap, X } from "lucide-react";
import { cn } from "@/lib/utils";

const nav = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/trends", label: "Trends", icon: TrendingUp },
  { href: "/clusters", label: "Clusters", icon: Network },
  { href: "/personas", label: "Personas", icon: Users },
  { href: "/search", label: "Search", icon: Search },
];

interface SidebarProps {
  open?: boolean;
  onClose?: () => void;
}

export default function Sidebar({ open = false, onClose }: SidebarProps) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "flex h-screen w-64 shrink-0 flex-col border-r bg-white",
        "fixed inset-y-0 left-0 z-50 transition-transform duration-200",
        "md:static md:z-auto md:w-56 md:translate-x-0",
        open ? "translate-x-0" : "-translate-x-full"
      )}
    >
      <div className="flex items-center gap-2 px-6 py-5 border-b">
        <Zap className="h-5 w-5 text-blue-600" />
        <span className="font-bold text-lg tracking-tight flex-1">Culturix</span>
        <button
          onClick={onClose}
          className="md:hidden rounded-md p-1 hover:bg-gray-100"
          aria-label="Close menu"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <nav className="flex flex-col gap-1 p-3 flex-1">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              onClick={onClose}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-blue-50 text-blue-700"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="px-4 py-3 border-t text-xs text-muted-foreground truncate">
        API: {process.env.NEXT_PUBLIC_API_URL ?? "localhost:8000"}
      </div>
    </aside>
  );
}

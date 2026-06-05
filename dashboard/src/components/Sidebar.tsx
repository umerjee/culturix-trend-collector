"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, TrendingUp, Network, Users, Search, Zap } from "lucide-react";
import { cn } from "@/lib/utils";

const nav = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/trends", label: "Trends", icon: TrendingUp },
  { href: "/clusters", label: "Clusters", icon: Network },
  { href: "/personas", label: "Personas", icon: Users },
  { href: "/search", label: "Search", icon: Search },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-56 flex-col border-r bg-white">
      {/* Logo */}
      <div className="flex items-center gap-2 px-6 py-5 border-b">
        <Zap className="h-5 w-5 text-blue-600" />
        <span className="font-bold text-lg tracking-tight">Culturix</span>
      </div>

      {/* Nav */}
      <nav className="flex flex-col gap-1 p-3 flex-1">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
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

      <div className="px-4 py-3 border-t text-xs text-muted-foreground">
        API: {process.env.NEXT_PUBLIC_API_URL ?? "localhost:8000"}
      </div>
    </aside>
  );
}

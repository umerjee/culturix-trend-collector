"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Zap, LayoutDashboard, TrendingUp, Layers, Users, Search, LogOut, History, ShieldCheck } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import type { UserRecord } from "@/lib/admin/types";

const NAV: { href: string; icon: React.ReactNode; label: string }[] = [
  { href: "/admin/overview", icon: <LayoutDashboard className="h-4 w-4" />, label: "Overview" },
  { href: "/admin/trends", icon: <TrendingUp className="h-4 w-4" />, label: "Trends" },
  { href: "/admin/clusters", icon: <Layers className="h-4 w-4" />, label: "Clusters" },
  { href: "/admin/personas", icon: <Users className="h-4 w-4" />, label: "Personas" },
  { href: "/admin/history", icon: <History className="h-4 w-4" />, label: "History" },
  { href: "/admin/validation", icon: <ShieldCheck className="h-4 w-4" />, label: "Validation" },
  { href: "/admin/users", icon: <Users className="h-4 w-4" />, label: "Users" },
  { href: "/admin/search", icon: <Search className="h-4 w-4" />, label: "Search" },
];

// Switching sections is now real Next.js navigation (bookmarkable URLs,
// working browser back/forward) instead of client-side view-state — this
// sidebar replaces AdminDashboard.tsx's old in-component `nav` array + `page`
// useState switch.
export default function AdminSidebar() {
  const pathname = usePathname();
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    fetchAdminData<UserRecord[]>("users")
      .then((users) => setPendingCount(users.filter((u) => !u.approved).length))
      .catch(() => setPendingCount(0));
  }, []);

  return (
    <aside className="w-48 shrink-0 bg-white border-r border-gray-100 flex flex-col">
      <div className="h-16 flex items-center gap-2 px-5 border-b border-gray-100">
        <Zap className="h-5 w-5 text-primary-600" />
        <span className="font-bold text-base tracking-tight text-gray-900">Culturix</span>
      </div>

      <nav className="flex-1 py-4 space-y-0.5 px-2">
        {NAV.map(({ href, icon, label }) => {
          const active = pathname === href || (href !== "/admin/overview" && pathname?.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors text-left ${
                active ? "bg-primary-50 text-primary-600" : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
              }`}
            >
              {icon}
              {label}
              {href === "/admin/users" && pendingCount > 0 && (
                <span className="ml-auto text-xs font-semibold text-amber-600">{pendingCount}</span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="p-3 border-t border-gray-100">
        <a
          href="/dashboard"
          className="flex items-center gap-2 px-3 py-2 text-xs text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <LogOut className="h-3.5 w-3.5" />
          Back to app
        </a>
      </div>
    </aside>
  );
}

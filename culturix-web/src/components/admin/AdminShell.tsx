"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import type { UserRecord } from "@/lib/admin/types";
import AdminSidebar from "./AdminSidebar";
import AdminTopBar from "./AdminTopBar";

// Below the lg breakpoint (phones and iPad portrait) the sidebar becomes a
// slide-in drawer opened from the top bar's menu button; from lg up (iPad
// landscape, laptops) it is the permanent left column it always was.
export default function AdminShell({ children }: { children: React.ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const pathname = usePathname();

  useEffect(() => {
    fetchAdminData<UserRecord[]>("users")
      .then((users) => setPendingCount(users.filter((u) => !u.approved).length))
      .catch(() => setPendingCount(0));
  }, []);

  useEffect(() => { setNavOpen(false); }, [pathname]);

  useEffect(() => {
    if (!navOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setNavOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", onKey);
    };
  }, [navOpen]);

  return (
    <div className="flex h-dvh bg-gray-50 overflow-hidden">
      <AdminSidebar pendingCount={pendingCount} className="hidden lg:flex w-52 shrink-0 border-r border-gray-100" />

      <div
        className={`lg:hidden fixed inset-0 z-40 transition-opacity duration-200 ${navOpen ? "opacity-100" : "opacity-0 pointer-events-none"}`}
        aria-hidden={!navOpen}
      >
        <button type="button" tabIndex={-1} aria-label="Close menu" onClick={() => setNavOpen(false)} className="absolute inset-0 bg-black/40" />
        <AdminSidebar
          pendingCount={pendingCount}
          onNavigate={() => setNavOpen(false)}
          onClose={() => setNavOpen(false)}
          mobile
          className={`absolute inset-y-0 left-0 w-72 max-w-[85vw] shadow-xl transition-transform duration-200 ${navOpen ? "translate-x-0" : "-translate-x-full"}`}
        />
      </div>

      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <AdminTopBar onMenu={() => setNavOpen(true)} menuOpen={navOpen} />
        <main className="flex-1 overflow-y-auto overflow-x-hidden px-4 py-5 sm:px-6 lg:px-8 lg:py-8">{children}</main>
      </div>
    </div>
  );
}

import Link from "next/link";
import { Zap, LayoutDashboard, TrendingUp, Settings, ShieldCheck, LogOut, HelpCircle } from "lucide-react";

type NavKey = "dashboard" | "performance" | "settings";

interface Props {
  active: NavKey;
  isSuperAdmin: boolean;
}

const ITEMS: { key: NavKey; href: string; icon: React.ReactNode; label: string }[] = [
  { key: "dashboard", href: "/dashboard", icon: <LayoutDashboard className="h-3.5 w-3.5" />, label: "Dashboard" },
  { key: "performance", href: "/dashboard/performance", icon: <TrendingUp className="h-3.5 w-3.5" />, label: "Performance" },
  { key: "settings", href: "/settings", icon: <Settings className="h-3.5 w-3.5" />, label: "Settings" },
];

export default function AppNav({ active, isSuperAdmin }: Props) {
  return (
    <header className="bg-white border-b border-gray-100 sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-2">
        <Link href="/dashboard" className="flex items-center gap-2 shrink-0">
          <Zap className="h-5 w-5 text-blue-600" />
          <span className="font-bold text-lg tracking-tight">Culturix</span>
        </Link>

        {/* overflow-x-auto is a safety net, not the primary fix — the tighter
            mobile padding below (px-2 vs px-3) is what keeps everything,
            including Sign out, on-screen without scrolling down to ~320px
            (iPhone SE) even for superadmins with the full item set. Without
            it, Sign out was pushed fully off-screen and unreachable. */}
        <nav className="flex items-center gap-0.5 sm:gap-1 overflow-x-auto">
          {ITEMS.map(({ key, href, icon, label }) => (
            <Link
              key={key}
              href={href}
              className={`inline-flex items-center gap-1.5 text-sm font-medium rounded-lg px-2 sm:px-3 py-2 shrink-0 transition-colors ${
                active === key
                  ? "bg-blue-50 text-blue-600"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
              }`}
            >
              {icon}
              <span className="hidden sm:inline">{label}</span>
            </Link>
          ))}
          <Link
            href="/how-it-works"
            target="_blank"
            rel="noopener noreferrer"
            title="How publishing works"
            className="inline-flex items-center gap-1.5 text-sm font-medium rounded-lg px-2 sm:px-3 py-2 shrink-0 text-gray-400 hover:bg-gray-50 hover:text-gray-600 transition-colors"
          >
            <HelpCircle className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">How it works</span>
          </Link>
          {isSuperAdmin && (
            <Link
              href="/admin"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-lg px-2 sm:px-3 py-2 shrink-0 hover:bg-indigo-50 transition-colors ml-1"
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Admin</span>
            </Link>
          )}
          <form action="/api/auth/signout" method="POST" className="ml-1 shrink-0">
            <button
              type="submit"
              title="Sign out"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-400 rounded-lg px-2 sm:px-3 py-2 hover:bg-gray-50 hover:text-gray-600 transition-colors"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </form>
        </nav>
      </div>
    </header>
  );
}

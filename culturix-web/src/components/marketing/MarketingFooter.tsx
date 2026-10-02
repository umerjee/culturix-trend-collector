import Link from "next/link";
import { Zap } from "lucide-react";
import NavText from "@/components/i18n/NavText";

// Public footer: watching plus the legal pages only. Creator product links must not return.
export default function MarketingFooter() {
  return (
    <footer className="py-8 px-4 sm:px-6 border-t border-white/5 bg-slate-950">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-sm">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-primary-400" />
          <span className="font-semibold text-gray-300">Culturix</span>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-x-4">
          <Link href="/world" className="inline-flex min-h-[44px] items-center text-gray-400 hover:text-gray-200 transition-colors"><NavText k="watchVideos" /></Link>
          <Link href="/privacy" className="inline-flex min-h-[44px] items-center text-gray-400 hover:text-gray-200 transition-colors"><NavText k="privacy" /></Link>
          <Link href="/terms" className="inline-flex min-h-[44px] items-center text-gray-400 hover:text-gray-200 transition-colors"><NavText k="terms" /></Link>
        </div>
        <p className="text-gray-400">© 2026 Culturix. <NavText k="rights" /></p>
      </div>
    </footer>
  );
}

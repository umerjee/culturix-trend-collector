"use client";

import { useEffect, useState } from "react";
import { Languages } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "fr", label: "Français" },
  { code: "de", label: "Deutsch" },
  { code: "es", label: "Español" },
];

export default function LanguageSwitcher() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [language, setLanguage] = useState(searchParams.get("lang") || "en");

  useEffect(() => {
    const saved = document.cookie.match(/(?:^|; )culturix_language=([^;]+)/)?.[1];
    const next = searchParams.get("lang") || saved || "en";
    setLanguage(LANGUAGES.some((item) => item.code === next) ? next : "en");
  }, [searchParams]);

  function changeLanguage(next: string) {
    setLanguage(next);
    document.cookie = `culturix_language=${next}; path=/; max-age=31536000; samesite=lax`;
    const params = new URLSearchParams(searchParams.toString());
    if (next === "en") params.delete("lang");
    else params.set("lang", next);
    const query = params.toString();
    router.push(`${pathname}${query ? `?${query}` : ""}`);
  }

  return (
    <label className="inline-flex items-center gap-1.5 text-xs text-gray-400" title="Language">
      <Languages className="h-3.5 w-3.5" />
      <span className="sr-only">Language</span>
      <select
        value={language}
        onChange={(event) => changeLanguage(event.target.value)}
        className="max-w-[5.5rem] bg-transparent text-xs text-inherit outline-none"
        aria-label="Language"
      >
        {LANGUAGES.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
      </select>
    </label>
  );
}

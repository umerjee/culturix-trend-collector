"use client";

import { useLocale, type NavKey } from "./LocaleProvider";

// Lets server components (MarketingHeader, MarketingFooter) render a localized label without
// becoming client components themselves.
export default function NavText({ k }: { k: NavKey }) {
  const { messages } = useLocale();
  return <>{messages.nav[k]}</>;
}

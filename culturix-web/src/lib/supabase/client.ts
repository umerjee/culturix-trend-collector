import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  // Fallback prevents build from crashing when env vars aren't set (e.g. CI preview deploys)
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL ?? "https://placeholder.supabase.co",
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "sb_publishable_placeholder"
  );
}

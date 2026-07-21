import { redirect } from "next/navigation";
import { Zap } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import OnboardingWizard from "@/components/OnboardingWizard";

const RAILWAY = "https://culturix-trend-collector-production.up.railway.app";

export default async function OnboardingPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) redirect("/signup");

  // Onboarding is first-time setup only — adding further niches happens in
  // Settings, so a user who already has a profile has nothing left to do
  // here (this is what let a returning sign-in bounce them back into the
  // wizard every time before the redirect-target fix in signup/page.tsx).
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || RAILWAY;
  let hasProfile = false;
  try {
    const res = await fetch(`${apiUrl}/users/${user.id}/content-profiles`, { cache: "no-store" });
    if (res.ok) {
      const profiles = await res.json();
      hasProfile = Array.isArray(profiles) && profiles.length > 0;
    }
  } catch {
    // Railway unreachable — let the wizard render rather than hard-blocking
  }
  // redirect() throws internally to signal Next.js — must not be inside the
  // try/catch above, or the catch would swallow that throw as a fetch error.
  if (hasProfile) redirect("/dashboard");

  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50 to-white">
      <nav className="p-6">
        <div className="flex items-center gap-2">
          <Zap className="h-5 w-5 text-blue-600" />
          <span className="font-bold text-lg tracking-tight">Culturix</span>
        </div>
      </nav>

      <div className="max-w-lg mx-auto px-4 py-8">
        <div className="text-center mb-10">
          <h1 className="text-2xl font-bold text-gray-900">Set up your content profile</h1>
          <p className="text-sm text-gray-500 mt-2">
            Takes 2 minutes. We&apos;ll personalize everything to your audience and niche.
          </p>
        </div>

        <OnboardingWizard userId={user.id} />
      </div>
    </div>
  );
}

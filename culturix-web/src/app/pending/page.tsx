import { redirect } from "next/navigation";
import { Clock, Zap } from "lucide-react";
import { createClient } from "@/lib/supabase/server";

export default async function PendingPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/signup");

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center px-4">
      <div className="bg-white rounded-2xl border border-gray-200 p-10 max-w-md w-full text-center shadow-sm">
        <div className="flex items-center justify-center gap-2 mb-8">
          <Zap className="h-5 w-5 text-blue-600" />
          <span className="font-bold text-lg tracking-tight">Culturix</span>
        </div>

        <div className="h-14 w-14 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-5">
          <Clock className="h-7 w-7 text-amber-500" />
        </div>

        <h1 className="text-xl font-bold text-gray-900 mb-2">Your account is under review</h1>
        <p className="text-sm text-gray-500 leading-relaxed mb-6">
          We manually review every new signup to keep Culturix bot-free.
          You&apos;ll get access as soon as we&apos;ve verified your account — usually within a few hours.
        </p>

        <p className="text-xs text-gray-400">
          Questions? Reach us at{" "}
          <a href="mailto:umer.ali79@gmail.com" className="text-blue-600 hover:underline">
            umer.ali79@gmail.com
          </a>
        </p>

        <form action="/api/auth/signout" method="POST" className="mt-8">
          <button
            type="submit"
            className="text-xs text-gray-400 hover:text-gray-600 underline"
          >
            Sign out
          </button>
        </form>
      </div>
    </div>
  );
}

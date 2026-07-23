import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import PublishLaunchCard from "@/components/PublishLaunchCard";

export const dynamic = "force-dynamic";

const RAILWAY = process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";

interface StageInfo {
  content_post_id: string;
  video_url: string | null;
  caption_text: string | null;
  target_platform: string;
  status: string;
  post_url: string | null;
}

export default async function PublishLaunchPage({ params }: { params: { postId: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect(`/signup?next=/publish/${params.postId}`);

  const res = await fetch(`${RAILWAY}/api/content-posts/${params.postId}/stage`, { cache: "no-store" });
  if (!res.ok) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="max-w-sm text-center space-y-2">
          <p className="text-lg font-semibold text-gray-900">Couldn&apos;t find this post</p>
          <p className="text-sm text-gray-500">It may have been removed, or the link is out of date.</p>
        </div>
      </div>
    );
  }
  const stage: StageInfo = await res.json();

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="mx-auto max-w-md">
        <PublishLaunchCard stage={stage} />
      </div>
    </div>
  );
}

import { cache } from "react";
import { notFound } from "next/navigation";
import MarketingHeader from "@/components/marketing/MarketingHeader";
import MarketingFooter from "@/components/marketing/MarketingFooter";
import FeatureWatchExperience from "@/components/world/FeatureWatchExperience";
import { RAILWAY_API_BASE } from "@/lib/config/api";
import type { WorldFeature } from "@/lib/worldTypes";

// cache(): generateMetadata and the page share one backend call per request. Next's own fetch
// dedupe can't be relied on here because of the abort signal.
const fetchFeature = cache(async (id: string): Promise<WorldFeature | null> => {
  try {
    const res = await fetch(`${RAILWAY_API_BASE}/world/features/${id}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
});

export async function generateMetadata({ params }: { params: { id: string } }) {
  const feature = await fetchFeature(params.id);
  if (!feature) return { title: "Culturix World" };
  return {
    title: `${feature.title || feature.subject_text} — Culturix World`,
    description: feature.hook_line || "A short, source-linked video from the AI video encyclopedia of the world, with a sense of humour.",
  };
}

// Server component: fetches the feature, then hands it to FeatureWatchExperience (client), which
// owns every event handler, autoplay and layout decision. Keyed by id so moving to the next
// video starts with fresh Next up state.
export default async function WorldFeaturePage({
  params, searchParams,
}: {
  params: { id: string }; searchParams: { autoplay?: string };
}) {
  const feature = await fetchFeature(params.id);
  if (!feature || !feature.final_video_url) notFound();

  return (
    <div className="min-h-screen bg-white">
      <MarketingHeader showCta={false} />
      <main className="max-w-6xl mx-auto px-4 sm:px-6">
        <FeatureWatchExperience key={feature.id} feature={feature} autoplay={searchParams.autoplay === "1"} />
      </main>
      <MarketingFooter />
    </div>
  );
}

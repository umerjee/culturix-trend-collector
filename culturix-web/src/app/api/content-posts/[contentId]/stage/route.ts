import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// GET /api/content-posts/[contentId]/stage  →  1-click launch page payload
// (here [contentId] is actually a content_post_id, not a generated_content_id —
// reuses the existing dynamic segment name to stay a sibling of [contentId]/route.ts)
export async function GET(
  _req: Request,
  { params }: { params: { contentId: string } }
) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const res = await fetch(
    `${RAILWAY}/api/content-posts/${params.contentId}/stage`,
    { cache: "no-store", signal: AbortSignal.timeout(10000) }
  );
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

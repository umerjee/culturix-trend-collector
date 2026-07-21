import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

// GET /api/content-posts/[contentId]?idea_index=N  →  poll endpoint
export async function GET(
  req: Request,
  { params }: { params: { contentId: string } }
) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const ideaIndex = searchParams.get("idea_index");
  const qs = ideaIndex ? `?idea_index=${ideaIndex}` : "";

  const res = await fetch(
    `${RAILWAY}/api/content-posts/${params.contentId}${qs}`,
    { cache: "no-store", signal: AbortSignal.timeout(10000) }
  );
  const data = await res.json().catch(() => []);
  return NextResponse.json(data, { status: res.status });
}

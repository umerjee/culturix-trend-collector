import { forwardEditorialPost } from "@/lib/admin/editorialProxy";

// Writing + fact-checking (+ one claim fix) is several LLM calls.
export const maxDuration = 300;

export async function POST(req: Request, { params }: { params: { id: string } }) {
  return forwardEditorialPost(req, `candidates/${encodeURIComponent(params.id)}/script`, { withUserId: true, timeoutMs: 280000 });
}

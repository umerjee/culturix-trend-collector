import { forwardEditorialPost } from "@/lib/admin/editorialProxy";

// A fact-check is one LLM call; allow it time.
export async function POST(req: Request, { params }: { params: { id: string } }) {
  return forwardEditorialPost(req, `candidates/${encodeURIComponent(params.id)}/grounding`, { timeoutMs: 120000 });
}

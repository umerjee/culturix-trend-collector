import { forwardEditorialPost } from "@/lib/admin/editorialProxy";

export async function POST(req: Request, { params }: { params: { id: string } }) {
  return forwardEditorialPost(req, `candidates/${encodeURIComponent(params.id)}/safety`);
}

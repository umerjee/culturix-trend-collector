import { forwardEditorialPost } from "@/lib/admin/editorialProxy";

export async function POST(req: Request, { params }: { params: { postId: string } }) {
  return forwardEditorialPost(req, `posts/${encodeURIComponent(params.postId)}/metrics`);
}

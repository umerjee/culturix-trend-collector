import { forwardEditorialPost } from "@/lib/admin/editorialProxy";

export async function POST(req: Request) {
  return forwardEditorialPost(req, "candidates/refresh");
}

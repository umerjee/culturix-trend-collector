// Shared-secret header sent on every Next -> FastAPI /admin/* call, so the
// backend rejects direct calls that skip this proxy layer entirely. Set
// ADMIN_API_SECRET (same value) on both Vercel and Railway — server-only env
// var, never NEXT_PUBLIC_.
export function adminApiHeaders(extra?: Record<string, string>): HeadersInit {
  return { ...(extra ?? {}), "x-admin-secret": process.env.ADMIN_API_SECRET ?? "" };
}

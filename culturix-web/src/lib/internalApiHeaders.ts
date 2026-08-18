// Shared-secret header for every Next -> FastAPI call outside /admin/* (which
// already has its own adminApiHeaders()/ADMIN_API_SECRET pair — see
// src/lib/admin/adminApiHeaders.ts). Railway's FastAPI backend has no
// authentication of its own on these routes: it trusts whatever user_id/
// brand_id a caller sends. This proxy layer resolves those from a verified
// Supabase session before forwarding, but the Railway URL itself isn't
// secret (it's the NEXT_PUBLIC_API_URL fallback, shipped in the browser
// bundle) — so without this header, anyone could skip this proxy entirely
// and call Railway directly with any user_id they want.
//
// INTERNAL_API_SECRET must be set (same value) on both Railway and Vercel —
// server-only env var, never NEXT_PUBLIC_. Until it's set on Railway,
// app/admin_auth.py::require_internal_secret fails OPEN (logs a warning,
// lets the request through) specifically so this rollout can't take the
// live app down mid-deploy — sending this header is safe/inert before
// that, and becomes load-bearing the moment the secret is configured.
//
// Every fetch() call in this directory's route.ts files that forwards to
// Railway (i.e. everything except the browser-redirect OAuth connect flows
// — those can't carry a header at all; see app/oauth_state.py for how
// those are protected instead) should use this.
export function internalApiHeaders(extra?: Record<string, string>): HeadersInit {
  return { ...(extra ?? {}), "x-internal-secret": process.env.INTERNAL_API_SECRET ?? "" };
}

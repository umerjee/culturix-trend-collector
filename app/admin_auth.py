import logging
import os
from fastapi import Header, HTTPException

logger = logging.getLogger("culturix.admin_auth")

# Defense-in-depth: the Next.js proxy layer (culturix-web/src/app/api/admin/**)
# already gates every /admin/* call behind a superadmin Supabase session, but
# these FastAPI routes have no auth of their own — anyone who discovers the
# Railway URL could call them directly. This shared-secret header, sent by
# every Next admin proxy route via adminApiHeaders(), closes that gap.
# ADMIN_API_SECRET must be set (same value) on both Railway and Vercel.
ADMIN_API_SECRET = os.getenv("ADMIN_API_SECRET", "")


def require_admin_secret(x_admin_secret: str = Header(default="")):
    if not ADMIN_API_SECRET or x_admin_secret != ADMIN_API_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


# Same gap as above, but for the rest of the API: app/routers/culturetoons.py
# (~90 routes) plus the Shopify/social/billing management endpoints in
# main.py all trust a plain user_id/brand_id request parameter with NO
# verification that the caller actually owns that identity — the Next.js
# proxy layer (culturix-web/src/app/api/**) resolves user_id from a
# verified Supabase session before forwarding, but nothing stops a caller
# from skipping that proxy and hitting Railway directly with any user_id
# they want (the Railway URL itself is not secret — it's the fallback
# literal baked into NEXT_PUBLIC_API_URL, shipped to the browser bundle).
# That's a full account-takeover primitive: read/write any user's
# characters, toons, brand settings, and billing-portal access using
# nothing but their user_id.
#
# INTERNAL_API_SECRET, sent via internalApiHeaders() on every proxied
# fetch() call (see culturix-web/src/lib/internalApiHeaders.ts), closes
# this the same way ADMIN_API_SECRET closes it for /admin/*.
#
# Deliberately FAIL-OPEN when unset (unlike require_admin_secret above,
# which fails closed) — this gate is being added retroactively to routes
# the live app already depends on for every request, so failing closed
# the moment this code ships would 403 the entire product until the env
# var is set on both Railway and Vercel, which nobody can do from inside
# this session. It logs a warning (once) instead. Set INTERNAL_API_SECRET
# on both platforms as soon as possible to actually close the gap — until
# then this is documentation of the fix, not the fix itself.
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "")
_warned_unset = False


def require_internal_secret(x_internal_secret: str = Header(default="")):
    global _warned_unset
    if not INTERNAL_API_SECRET:
        if not _warned_unset:
            logger.warning(
                "INTERNAL_API_SECRET is not set — every non-admin API route is currently reachable by anyone "
                "who knows or guesses a user_id, with no authentication at all. Set INTERNAL_API_SECRET on "
                "both Railway and Vercel (see app/admin_auth.py) to close this."
            )
            _warned_unset = True
        return
    if x_internal_secret != INTERNAL_API_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

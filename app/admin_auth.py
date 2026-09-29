import hmac
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
    # hmac.compare_digest, not !=, so matching this secret can't be sped up
    # by timing how long the comparison takes on a byte-by-byte mismatch —
    # mostly theoretical over real-world HTTP jitter, but free to close
    # properly rather than lean on that.
    if not ADMIN_API_SECRET or not hmac.compare_digest(x_admin_secret, ADMIN_API_SECRET):
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
# Fail closed when unset. The Railway API URL is public and every route
# protected by this dependency accepts user_id/brand_id values, so an unset
# secret would otherwise turn those parameters into an account-data access
# primitive. Configure INTERNAL_API_SECRET on both Railway and Vercel before
# deploying this change; an unavailable product is safer than cross-account
# reads and writes.
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "")


def require_internal_secret(x_internal_secret: str = Header(default="")):
    if not INTERNAL_API_SECRET or not hmac.compare_digest(x_internal_secret, INTERNAL_API_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")

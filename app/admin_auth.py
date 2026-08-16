import os
from fastapi import Header, HTTPException

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

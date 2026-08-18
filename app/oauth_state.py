"""HMAC-signs the `state` parameter carried through third-party OAuth
round trips (social platforms — app/main.py's social_connect/
social_callback — and Shopify — shopify_connect/shopify_callback).

Both flows previously passed a raw, unsigned user_id (plus, for social,
optional profile/brand scope ids) straight through `state` on the
assumption that this app has no server-side session of its own to check
against. That assumption undersold the actual risk: `state` isn't just
opaque round-trip data, it's the value BOTH callbacks trust to decide
*whose* account a freshly-authorized connection gets attached to — and an
attacker doesn't need to forge the callback itself (Shopify's callback is
separately HMAC-verified with Shopify's own client secret; the social
providers' code-exchange step is a normal OAuth code redemption) to abuse
this. They just call the *connect* endpoint directly with
`user_id=<victim>`, complete their OWN real consent flow with their OWN
account, and the callback dutifully attaches their account to the
victim's — hijacking that user's outbound publishing pipeline. Signing
`state` server-side (here) means an attacker can no longer choose whose
identity a connection lands on, since they can't produce a valid signature
without the shared secret.

OAUTH_STATE_SECRET must be set for either flow to work at all — unlike
app/admin_auth.py's require_admin_secret (deliberately fail-open when
unconfigured, to avoid taking down the whole live app the moment that gate
shipped), this only touches the OAuth *connect* code path, not every
existing request, so failing closed here is safe: it blocks new/re
connections until configured rather than silently leaving the spoofing
gap open. Existing already-connected accounts are unaffected either way.
"""
import hashlib
import hmac
import os
import time

_SECRET_ENV = "OAUTH_STATE_SECRET"
_MAX_AGE_SECONDS = 600  # 10 minutes is generous for a consent-screen round trip


class OAuthStateError(Exception):
    pass


def _secret() -> bytes:
    secret = os.getenv(_SECRET_ENV, "")
    if not secret:
        raise RuntimeError(f"{_SECRET_ENV} must be set")
    return secret.encode("utf-8")


def sign(payload: str) -> str:
    """payload must not itself contain '.' — none of this codebase's state
    payloads do (UUIDs and ':'-joined UUIDs only)."""
    ts = str(int(time.time()))
    msg = f"{payload}.{ts}"
    sig = hmac.new(_secret(), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{msg}.{sig}"


def verify_and_unwrap(signed: str) -> str:
    """Returns the original payload. Raises OAuthStateError on any
    tampering, expiry, or malformed input — callers should treat this the
    same as a missing/invalid state param, not a 500."""
    if not signed:
        raise OAuthStateError("empty state")
    parts = signed.rsplit(".", 2)
    if len(parts) != 3:
        raise OAuthStateError("malformed state")
    payload, ts, sig = parts
    expected = hmac.new(_secret(), f"{payload}.{ts}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise OAuthStateError("signature mismatch")
    try:
        age = time.time() - int(ts)
    except ValueError:
        raise OAuthStateError("malformed timestamp")
    if age > _MAX_AGE_SECONDS or age < -30:  # small negative slack for clock skew
        raise OAuthStateError("state expired")
    return payload

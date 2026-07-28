"""Shopify OAuth (custom distribution) — the app is installed by each new
brand via a Shopify-issued install link (custom distribution, not a public
App Store listing), then goes through the standard OAuth authorize/callback/
token-exchange cycle. This is deliberately not App-Store-public: Shopify's
mandatory GDPR compliance webhooks (customers/data_request, customers/
redact, shop/redact) are only required for App-Store-listed apps, not
custom-distribution ones, so skipping App Store listing for now avoids that
compliance surface until this is actually ready to be found by strangers.

Shopify's offline access tokens (what this flow requests, implicitly, by
being a background/server-side integration rather than embedded) don't
expire and have no refresh token — unlike most OAuth providers in
app/social/, there's no refresh_access_token step here.

Requires SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET (from the app's Dev
Dashboard Settings page) as env vars.
"""
import hashlib
import hmac
import os
import re
from urllib.parse import urlencode
import httpx

_SCOPES = "read_products"
_SHOP_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*\.myshopify\.com$")


def is_valid_shop_domain(domain: str) -> bool:
    """Defensive format check on `shop`, independent of the HMAC check below —
    both the value Shopify redirects back with and the value a user types into
    our own connect form get built straight into outbound request URLs."""
    return bool(_SHOP_DOMAIN_RE.match(domain))


def _client_id() -> str:
    v = os.environ.get("SHOPIFY_CLIENT_ID", "")
    if not v:
        raise RuntimeError("SHOPIFY_CLIENT_ID not set")
    return v


def _client_secret() -> str:
    v = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
    if not v:
        raise RuntimeError("SHOPIFY_CLIENT_SECRET not set")
    return v


def get_authorize_url(shop_domain: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": _client_id(),
        "scope": _SCOPES,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"https://{shop_domain}/admin/oauth/authorize?{urlencode(params)}"


def verify_hmac(query_params: dict) -> bool:
    """Confirms a callback's query params genuinely came from Shopify (signed
    with our client secret), not a forged redirect — see Shopify's OAuth
    security docs. Must pass before `shop`/`code` from a callback are trusted."""
    try:
        secret = _client_secret()
    except RuntimeError:
        return False
    provided = query_params.get("hmac", "")
    if not provided:
        return False
    params = {k: v for k, v in query_params.items() if k not in ("hmac", "signature")}
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    computed = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, provided)


def exchange_code(shop_domain: str, code: str) -> str:
    resp = httpx.post(
        f"https://{shop_domain}/admin/oauth/access_token",
        json={"client_id": _client_id(), "client_secret": _client_secret(), "code": code},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Shopify token exchange returned no access_token: {data}")
    return token

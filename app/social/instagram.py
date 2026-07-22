"""Instagram OAuth (Instagram Login, not the older Facebook-Login-for-
Business flow — the newer `instagram_business_*` scopes, since the old
scope values are being deprecated) + Content Publishing API.

Hand-rolled via httpx, matching this codebase's existing style.

IMPORTANT — like TikTokProvider, this has NOT been live-tested: no real
Instagram/Meta developer app credentials existed when this was written.
Every endpoint/field/response shape below was sourced directly from Meta's
developer docs (fetched 2026-07-22), not guessed.

Architecturally different from YouTube/TikTok: Instagram's publish API does
NOT accept raw video bytes. It requires the video to already be hosted at a
public URL, which it then fetches itself. publish() uploads the given
video_bytes to this codebase's existing Supabase Storage helper
(app/media/storage.py — already used for cached trend thumbnails) to get a
public URL, THEN hands that URL to Instagram — a "container" is created
referencing it, then published as a separate step.
"""
import os
import re
import time
from urllib.parse import urlencode
from typing import Optional

import httpx

from app.social.base import AccountInfo, OAuthProvider, PostMetrics, TokenResult

# Source: Meta developer docs, "Instagram API with Instagram Login" (fetched 2026-07-22)
_AUTH_URL = "https://www.instagram.com/oauth/authorize"
_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
_GRAPH_BASE = "https://graph.instagram.com"
_API_VERSION = "v21.0"
_SCOPES = "instagram_business_basic,instagram_business_content_publish"

# Instagram's public permalink uses a shortcode (e.g. "Cxyz123abc"), NOT the
# numeric media ID the Graph API needs for metrics lookups — they're
# unrelated strings, not two encodings of the same value. publish() below
# appends the real numeric ID as a URL fragment (#mid=...) on our own
# stored post_url so fetch_post_metrics can recover it reliably; a fragment
# doesn't change what the link actually opens to. A URL without that
# fragment (e.g. a real Instagram link a user pasted in manually) can't be
# resolved to a numeric ID without an extra oEmbed lookup this provider
# doesn't implement yet — see fetch_post_metrics's ValueError below.
_OWN_MEDIA_ID_PATTERN = re.compile(r"#mid=(\d+)")

# Publishing is async on Instagram's side too — poll the container's status
# before calling media_publish (publishing a not-yet-ready container fails).
_CONTAINER_POLL_ATTEMPTS = 20
_CONTAINER_POLL_INTERVAL_SECONDS = 3


class InstagramProvider(OAuthProvider):
    def __init__(self) -> None:
        self._client_id = os.environ.get("INSTAGRAM_CLIENT_ID", "")
        self._client_secret = os.environ.get("INSTAGRAM_CLIENT_SECRET", "")
        self._redirect_base = os.environ.get("OAUTH_REDIRECT_BASE_URL", "")
        if not (self._client_id and self._client_secret and self._redirect_base):
            raise RuntimeError(
                "INSTAGRAM_CLIENT_ID, INSTAGRAM_CLIENT_SECRET, and "
                "OAUTH_REDIRECT_BASE_URL must all be set"
            )

    @property
    def _redirect_uri(self) -> str:
        return f"{self._redirect_base}/api/social/instagram/callback"

    def get_authorize_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenResult:
        # Step 1: short-lived (1hr) token — code exchange only accepts
        # form-encoded POST, not JSON.
        resp = httpx.post(_TOKEN_URL, data={
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": self._redirect_uri,
            "code": code,
        }, timeout=30)
        resp.raise_for_status()
        short = resp.json()
        ig_user_id = short.get("user_id")

        # Step 2: exchange for a 60-day long-lived token immediately — we
        # have nowhere to use a 1-hour token productively in this codebase's
        # background-task publish flow.
        long_resp = httpx.get(f"{_GRAPH_BASE}/access_token", params={
            "grant_type": "ig_exchange_token",
            "client_secret": self._client_secret,
            "access_token": short["access_token"],
        }, timeout=30)
        long_resp.raise_for_status()
        long_lived = long_resp.json()

        username = self._fetch_username(long_lived["access_token"])
        return TokenResult(
            access_token=long_lived["access_token"],
            refresh_token=None,  # Instagram has no separate refresh token — see refresh_access_token
            expires_in_seconds=long_lived.get("expires_in"),
            platform_account_id=str(ig_user_id) if ig_user_id else None,
            platform_username=username,
        )

    def refresh_access_token(self, refresh_token: str) -> TokenResult:
        # Instagram's long-lived tokens refresh themselves (no separate
        # refresh_token value — the caller passes the current long-lived
        # access_token here instead, same value stored as "refresh_token"
        # by resolve_active_account's caller). Must be at least 24h old and
        # not yet expired.
        resp = httpx.get(f"{_GRAPH_BASE}/refresh_access_token", params={
            "grant_type": "ig_refresh_token",
            "access_token": refresh_token,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return TokenResult(
            access_token=data["access_token"],
            refresh_token=data["access_token"],  # same value — see note above
            expires_in_seconds=data.get("expires_in"),
        )

    def _fetch_username(self, access_token: str) -> Optional[str]:
        resp = httpx.get(f"{_GRAPH_BASE}/me", params={
            "fields": "username",
            "access_token": access_token,
        }, timeout=20)
        resp.raise_for_status()
        return resp.json().get("username")

    def _fetch_user_id(self, access_token: str) -> str:
        resp = httpx.get(f"{_GRAPH_BASE}/me", params={
            "fields": "user_id",
            "access_token": access_token,
        }, timeout=20)
        resp.raise_for_status()
        return str(resp.json()["user_id"])

    def verify(self, access_token: str) -> AccountInfo:
        # Combines _fetch_username/_fetch_user_id's two separate calls into
        # one — same /me endpoint, just both fields requested at once.
        resp = httpx.get(f"{_GRAPH_BASE}/me", params={
            "fields": "username,user_id",
            "access_token": access_token,
        }, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("user_id"):
            raise RuntimeError("Instagram returned no user for this token")
        return AccountInfo(platform_account_id=str(data["user_id"]), platform_username=data.get("username"))

    def fetch_post_metrics(self, access_token: str, post_url: str) -> PostMetrics:
        match = _OWN_MEDIA_ID_PATTERN.search(post_url)
        if not match:
            raise ValueError(
                f"Could not resolve an Instagram media ID from URL: {post_url} — metrics "
                f"tracking only works for posts published through Culturix (publish() encodes "
                f"the numeric ID as a URL fragment); a manually-pasted Instagram link has no "
                f"way to resolve its numeric media ID without an additional oEmbed lookup, "
                f"which isn't implemented"
            )
        media_id = match.group(1)

        resp = httpx.get(
            f"{_GRAPH_BASE}/{_API_VERSION}/{media_id}",
            params={"fields": "like_count,comments_count", "access_token": access_token},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return PostMetrics(
            platform_post_id=media_id,
            views=None,  # not exposed on this field set without extra Business Discovery scopes
            likes=data.get("like_count"),
            comments=data.get("comments_count"),
            shares=None,  # Instagram Graph API has no share-count field
        )

    def publish(self, access_token: str, video_bytes: bytes, title: str, description: str) -> PostMetrics:
        from app.media import storage

        # Instagram fetches the video itself — it must already be at a
        # public URL, not sent as bytes in this request.
        public_url = storage.upload(video_bytes, f"instagram-publish/{int(time.time())}.mp4", "video/mp4")

        ig_user_id = self._fetch_user_id(access_token)

        init_resp = httpx.post(
            f"{_GRAPH_BASE}/{_API_VERSION}/{ig_user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": public_url,
                "caption": description[:2200] or title[:2200],
                # Every video this codebase publishes is Kling-generated —
                # always disclose, never conditional (matches TikTok's
                # is_aigc and YouTube's containsSyntheticMedia).
                "is_ai_generated": "true",  # form-encoded POST — string, not a JSON bool
                "access_token": access_token,
            },
            timeout=30,
        )
        init_resp.raise_for_status()
        container_id = init_resp.json()["id"]

        self._wait_until_container_ready(access_token, container_id)

        publish_resp = httpx.post(
            f"{_GRAPH_BASE}/{_API_VERSION}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
            timeout=30,
        )
        publish_resp.raise_for_status()
        media_id = publish_resp.json()["id"]

        # No real share-URL construction available without an extra lookup
        # (permalink field) — fetch it in the same call rather than a
        # second round trip.
        permalink_resp = httpx.get(
            f"{_GRAPH_BASE}/{_API_VERSION}/{media_id}",
            params={"fields": "permalink", "access_token": access_token},
            timeout=20,
        )
        permalink_resp.raise_for_status()
        permalink = permalink_resp.json().get("permalink") or f"https://www.instagram.com/reel/{media_id}"
        # Fragment doesn't change what the link opens to — see the
        # _OWN_MEDIA_ID_PATTERN comment for why it's needed.
        post_url_with_id = f"{permalink}#mid={media_id}"

        return PostMetrics(platform_post_id=post_url_with_id, views=0, likes=0, comments=0, shares=0)

    def _wait_until_container_ready(self, access_token: str, container_id: str) -> None:
        for _ in range(_CONTAINER_POLL_ATTEMPTS):
            resp = httpx.get(
                f"{_GRAPH_BASE}/{_API_VERSION}/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
                timeout=20,
            )
            resp.raise_for_status()
            status = resp.json().get("status_code")

            if status == "FINISHED":
                return
            if status == "ERROR":
                raise RuntimeError(f"Instagram media container {container_id} failed to process")

            time.sleep(_CONTAINER_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"Instagram media container {container_id} did not finish processing within "
            f"{_CONTAINER_POLL_ATTEMPTS * _CONTAINER_POLL_INTERVAL_SECONDS}s"
        )

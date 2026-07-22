"""X/Twitter OAuth 2.0 (PKCE) + API v2 — connect a user's account for
posting and reading tweet metrics.

Hand-rolled via httpx, matching this codebase's existing style.

IMPORTANT — like TikTokProvider/InstagramProvider, this has NOT been
live-tested: no real credentials existed when this was written. Every
endpoint/field/response shape was sourced from X's developer docs (fetched
2026-07-22), not guessed.

X requires PKCE (S256) even for confidential (server-side, client-secret-
holding) clients like this one. PKCE's usual security purpose — protecting
public clients that have no secret — doesn't apply here, so this uses a
FIXED code_verifier/code_challenge pair rather than a per-session random
one. That fits OAuthProvider's existing two-call shape (get_authorize_url
and exchange_code are separate, statelessly-independent HTTP requests,
sometimes minutes apart, with nothing to carry a per-request verifier
across) without changing that interface for every other provider.

ALSO IMPORTANT — as of 2026, X's API has NO free tier for new developer
accounts: posting is pay-per-use (~$0.015/tweet, more with a URL or media),
credits purchased upfront. This is a real ongoing cost per post, not a
one-time setup like the other three platforms.

Media upload uses the older, separate v1.1 chunked upload endpoint
(upload.twitter.com) — X has not moved this specific flow to v2.
"""
import base64
import hashlib
import os
import re
import time
from urllib.parse import urlencode
from typing import Optional

import httpx

from app.social.base import AccountInfo, OAuthProvider, PostMetrics, TokenResult

# Source: docs.x.com (fetched 2026-07-22)
_AUTH_URL = "https://twitter.com/i/oauth2/authorize"
_TOKEN_URL = "https://api.x.com/2/oauth2/token"
_API_BASE = "https://api.x.com/2"
_MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
_SCOPES = "tweet.read tweet.write users.read offline.access media.write"

# Fixed PKCE pair — see module docstring for why static is fine for a
# confidential client. Not a secret (code_verifier is sent in the open on
# the token exchange anyway); doesn't need env-var treatment.
_CODE_VERIFIER = "culturix-x-oauth-static-pkce-verifier-2026-do-not-rotate-lightly"
_CODE_CHALLENGE = base64.urlsafe_b64encode(
    hashlib.sha256(_CODE_VERIFIER.encode()).digest()
).decode().rstrip("=")

_TWEET_ID_PATTERN = re.compile(r"/status(?:es)?/(\d+)")

_MEDIA_POLL_ATTEMPTS = 20
_MEDIA_POLL_FALLBACK_INTERVAL_SECONDS = 3
_APPEND_CHUNK_SIZE = 4 * 1024 * 1024  # 4MB, well under X's per-chunk limits


class TwitterProvider(OAuthProvider):
    def __init__(self) -> None:
        self._client_id = os.environ.get("TWITTER_CLIENT_ID", "")
        self._client_secret = os.environ.get("TWITTER_CLIENT_SECRET", "")
        self._redirect_base = os.environ.get("OAUTH_REDIRECT_BASE_URL", "")
        if not (self._client_id and self._client_secret and self._redirect_base):
            raise RuntimeError(
                "TWITTER_CLIENT_ID, TWITTER_CLIENT_SECRET, and "
                "OAUTH_REDIRECT_BASE_URL must all be set"
            )

    @property
    def _redirect_uri(self) -> str:
        return f"{self._redirect_base}/api/social/twitter/callback"

    def get_authorize_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": _SCOPES,
            "state": state,
            "code_challenge": _CODE_CHALLENGE,
            "code_challenge_method": "S256",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenResult:
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "code": code,
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "code_verifier": _CODE_VERIFIER,
            },
            auth=(self._client_id, self._client_secret),  # confidential client HTTP Basic auth
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        username = self._fetch_username(data["access_token"])
        return TokenResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),  # only present if offline.access was granted
            expires_in_seconds=data.get("expires_in"),
            platform_username=username,
        )

    def refresh_access_token(self, refresh_token: str) -> TokenResult:
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
            },
            auth=(self._client_id, self._client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return TokenResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in_seconds=data.get("expires_in"),
        )

    def _fetch_username(self, access_token: str) -> Optional[str]:
        resp = httpx.get(
            f"{_API_BASE}/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("username")

    def verify(self, access_token: str) -> AccountInfo:
        # /users/me already returns id/name/username in its default field
        # set — same call _fetch_username makes, just also reading `id`.
        resp = httpx.get(
            f"{_API_BASE}/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json().get("data")
        if not data:
            raise RuntimeError("X returned no user for this token")
        return AccountInfo(platform_account_id=data.get("id"), platform_username=data.get("username"))

    def fetch_post_metrics(self, access_token: str, post_url: str) -> PostMetrics:
        match = _TWEET_ID_PATTERN.search(post_url)
        if not match:
            raise ValueError(f"Could not parse a tweet ID from URL: {post_url}")
        tweet_id = match.group(1)

        resp = httpx.get(
            f"{_API_BASE}/tweets/{tweet_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"tweet.fields": "public_metrics"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json().get("data")
        if not data:
            raise RuntimeError(f"X returned no tweet for id {tweet_id}")
        m = data.get("public_metrics") or {}
        return PostMetrics(
            platform_post_id=tweet_id,
            views=m.get("impression_count"),
            likes=m.get("like_count"),
            comments=m.get("reply_count"),
            shares=m.get("retweet_count"),
        )

    def publish(self, access_token: str, video_bytes: bytes, title: str, description: str) -> PostMetrics:
        media_id = self._upload_media(access_token, video_bytes)

        resp = httpx.post(
            f"{_API_BASE}/tweets",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"text": (description or title)[:280], "media": {"media_ids": [media_id]}},
            timeout=30,
        )
        resp.raise_for_status()
        tweet_id = resp.json()["data"]["id"]

        return PostMetrics(platform_post_id=tweet_id, views=0, likes=0, comments=0, shares=0)

    def _upload_media(self, access_token: str, video_bytes: bytes) -> str:
        headers = {"Authorization": f"Bearer {access_token}"}

        init_resp = httpx.post(_MEDIA_UPLOAD_URL, headers=headers, data={
            "command": "INIT",
            "media_type": "video/mp4",
            "total_bytes": len(video_bytes),
            "media_category": "tweet_video",
        }, timeout=30)
        init_resp.raise_for_status()
        media_id = init_resp.json()["media_id_string"]

        for segment_index, offset in enumerate(range(0, len(video_bytes), _APPEND_CHUNK_SIZE)):
            chunk = video_bytes[offset:offset + _APPEND_CHUNK_SIZE]
            append_resp = httpx.post(
                _MEDIA_UPLOAD_URL,
                headers=headers,
                data={"command": "APPEND", "media_id": media_id, "segment_index": segment_index},
                files={"media": ("chunk.mp4", chunk, "application/octet-stream")},
                timeout=60,
            )
            append_resp.raise_for_status()

        finalize_resp = httpx.post(_MEDIA_UPLOAD_URL, headers=headers, data={
            "command": "FINALIZE", "media_id": media_id,
        }, timeout=30)
        finalize_resp.raise_for_status()
        finalize_data = finalize_resp.json()

        processing_info = finalize_data.get("processing_info")
        if processing_info:
            self._wait_for_processing(access_token, media_id, processing_info)

        return media_id

    def _wait_for_processing(self, access_token: str, media_id: str, processing_info: dict) -> None:
        headers = {"Authorization": f"Bearer {access_token}"}
        info = processing_info
        for _ in range(_MEDIA_POLL_ATTEMPTS):
            state = info.get("state")
            if state == "succeeded":
                return
            if state == "failed":
                raise RuntimeError(f"X media processing failed for {media_id}: {info.get('error')}")

            time.sleep(info.get("check_after_secs") or _MEDIA_POLL_FALLBACK_INTERVAL_SECONDS)

            status_resp = httpx.get(_MEDIA_UPLOAD_URL, headers=headers, params={
                "command": "STATUS", "media_id": media_id,
            }, timeout=20)
            status_resp.raise_for_status()
            info = status_resp.json().get("processing_info") or {"state": "succeeded"}

        raise RuntimeError(f"X media processing for {media_id} did not complete in time")

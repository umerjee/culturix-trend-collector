"""TikTok OAuth + Content Posting API — connect a user's account for both
reading public video statistics and publishing on their behalf.

Hand-rolled via httpx, matching this codebase's existing style (Kling's
manual JWT signing, Qwen's direct httpx calls, YouTubeProvider's own
hand-rolled OAuth) rather than pulling in a provider SDK.

IMPORTANT — unlike YouTubeProvider, this has NOT been live-tested against
the real API: TikTok's Content Posting API requires the developer to
register an app and get it approved for the `video.publish` scope before
any of this can actually run, and that approval didn't exist at the time
this was written. Every endpoint URL, field name, and response shape below
was sourced directly from TikTok's own developer documentation (fetched
2026-07-22, see the endpoint comments), not guessed — but "matches the
docs" and "confirmed working against a live account" are different levels
of confidence (this codebase's Instagram ScrapeCreators integration is a
concrete example of docs and live behavior diverging once). Treat this as
needing the same live-verification pass YouTubeProvider already got, the
first time real TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET credentials exist.

Publishing is asynchronous on TikTok's side (unlike YouTube's effectively-
synchronous upload) — init, upload, then poll a status endpoint until the
video finishes processing. publish() polls in-process with a bounded
number of attempts since it already runs inside a background task
(app.social.service.publish_and_record), not a live request/response
cycle — a real HTTP request would need a different (webhook or
fire-and-poll-separately) design, but that's not what's happening here.
"""
import os
import re
import time
from urllib.parse import urlencode
from typing import Optional

import httpx

from app.social.base import OAuthProvider, PostMetrics, TokenResult

# Source: https://developers.tiktok.com/doc/login-kit-web (fetched 2026-07-22)
_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
# Source: https://developers.tiktok.com/doc/oauth-user-access-token-management
_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_API_BASE = "https://open.tiktokapis.com/v2"
_SCOPES = "user.info.basic,video.publish,video.list"

_VIDEO_ID_PATTERN = re.compile(r"/video/(\d+)")

# TikTok publishing is async — poll status/fetch up to this many times,
# waiting this long between attempts, before giving up (the video may still
# complete on TikTok's side after this; publish_and_record just won't know
# the final post_id and will mark the ContentPost row failed).
_STATUS_POLL_ATTEMPTS = 20
_STATUS_POLL_INTERVAL_SECONDS = 3


class TikTokProvider(OAuthProvider):
    def __init__(self) -> None:
        self._client_key = os.environ.get("TIKTOK_CLIENT_KEY", "")
        self._client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
        self._redirect_base = os.environ.get("OAUTH_REDIRECT_BASE_URL", "")
        if not (self._client_key and self._client_secret and self._redirect_base):
            raise RuntimeError(
                "TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, and "
                "OAUTH_REDIRECT_BASE_URL must all be set"
            )

    @property
    def _redirect_uri(self) -> str:
        return f"{self._redirect_base}/api/social/tiktok/callback"

    def get_authorize_url(self, state: str) -> str:
        params = {
            "client_key": self._client_key,
            "response_type": "code",
            "scope": _SCOPES,
            "redirect_uri": self._redirect_uri,
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenResult:
        resp = httpx.post(_TOKEN_URL, data={
            "client_key": self._client_key,
            "client_secret": self._client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self._redirect_uri,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        username = self._fetch_username(data["access_token"])
        return TokenResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in_seconds=data.get("expires_in"),
            platform_account_id=data.get("open_id"),
            platform_username=username,
        )

    def refresh_access_token(self, refresh_token: str) -> TokenResult:
        resp = httpx.post(_TOKEN_URL, data={
            "client_key": self._client_key,
            "client_secret": self._client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return TokenResult(
            access_token=data["access_token"],
            # TikTok DOES reissue a refresh_token on every exchange (unlike
            # Google) — the caller should persist this new one, not reuse
            # the old value.
            refresh_token=data.get("refresh_token"),
            expires_in_seconds=data.get("expires_in"),
        )

    def _fetch_username(self, access_token: str) -> Optional[str]:
        resp = httpx.get(
            f"{_API_BASE}/user/info/",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "display_name"},
            timeout=20,
        )
        resp.raise_for_status()
        user = resp.json().get("data", {}).get("user") or {}
        return user.get("display_name")

    def fetch_post_metrics(self, access_token: str, post_url: str) -> PostMetrics:
        match = _VIDEO_ID_PATTERN.search(post_url)
        if not match:
            raise ValueError(f"Could not parse a TikTok video ID from URL: {post_url}")
        video_id = match.group(1)

        resp = httpx.post(
            f"{_API_BASE}/video/query/",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            params={"fields": "id,view_count,like_count,comment_count,share_count"},
            json={"filters": {"video_ids": [video_id]}},
            timeout=20,
        )
        resp.raise_for_status()
        videos = resp.json().get("data", {}).get("videos") or []
        if not videos:
            raise RuntimeError(f"TikTok returned no video for id {video_id}")
        v = videos[0]
        return PostMetrics(
            platform_post_id=video_id,
            views=v.get("view_count"),
            likes=v.get("like_count"),
            comments=v.get("comment_count"),
            shares=v.get("share_count"),
        )

    def publish(self, access_token: str, video_bytes: bytes, title: str, description: str) -> PostMetrics:
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        init_resp = httpx.post(
            f"{_API_BASE}/post/publish/video/init/",
            headers=headers,
            json={
                "post_info": {
                    "title": title[:150],
                    "privacy_level": os.environ.get("TIKTOK_PUBLISH_PRIVACY_LEVEL", "SELF_ONLY"),
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": len(video_bytes),
                    "chunk_size": len(video_bytes),
                    "total_chunk_count": 1,
                },
            },
            timeout=30,
        )
        init_resp.raise_for_status()
        init_data = init_resp.json()["data"]
        publish_id = init_data["publish_id"]
        upload_url = init_data["upload_url"]

        upload_resp = httpx.put(
            upload_url,
            headers={
                "Content-Range": f"bytes 0-{len(video_bytes) - 1}/{len(video_bytes)}",
                "Content-Type": "video/mp4",
            },
            content=video_bytes,
            timeout=180,
        )
        upload_resp.raise_for_status()

        # Poll first — only worth fetching the username (a separate call) if
        # the publish actually succeeded; no point paying for it on a failure.
        post_id = self._poll_until_complete(access_token, publish_id)
        username = self._fetch_username(access_token)
        post_url = f"https://www.tiktok.com/@{username}/video/{post_id}" if username else post_id

        # A fresh post has nothing to report yet — same convention as
        # YouTubeProvider.publish()'s zeroed metrics.
        return PostMetrics(platform_post_id=post_url, views=0, likes=0, comments=0, shares=0)

    def _poll_until_complete(self, access_token: str, publish_id: str) -> str:
        for _ in range(_STATUS_POLL_ATTEMPTS):
            resp = httpx.post(
                f"{_API_BASE}/post/publish/status/fetch/",
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json={"publish_id": publish_id},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            status = data.get("status")

            if status == "PUBLISH_COMPLETE":
                # Field name "publicaly_available_post_id" (sic) is TikTok's
                # own documented spelling, not a typo introduced here.
                post_ids = data.get("publicaly_available_post_id") or []
                if not post_ids:
                    raise RuntimeError(f"TikTok publish {publish_id} completed with no post id returned")
                return str(post_ids[0])
            if status == "FAILED":
                raise RuntimeError(f"TikTok publish {publish_id} failed: {data.get('fail_reason')}")

            time.sleep(_STATUS_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"TikTok publish {publish_id} did not complete within "
            f"{_STATUS_POLL_ATTEMPTS * _STATUS_POLL_INTERVAL_SECONDS}s — it may still finish "
            f"on TikTok's side; check manually via /v2/post/publish/status/fetch/"
        )

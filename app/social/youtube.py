"""YouTube OAuth — connect a user's channel for both reading public video
statistics and publishing on their behalf (both scopes requested in one
consent grant so the user only connects once).

Hand-rolled via httpx rather than google-auth-oauthlib/google-api-python-client,
consistent with this codebase's existing style of hand-rolled auth (Kling's
manual JWT signing, Qwen's direct httpx calls) instead of pulling in provider
SDKs.
"""
import os
import json
import re
from urllib.parse import urlencode
from typing import Optional

import httpx

from app.social.base import OAuthProvider, PostMetrics, TokenResult

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_API_BASE = "https://www.googleapis.com/youtube/v3"
_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_SCOPES = "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload"

_VIDEO_ID_PATTERNS = [
    re.compile(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})"),
]

# Conservative default so a first real upload isn't blasted to the public
# feed before this has been exercised end-to-end — override once ready.
_DEFAULT_PRIVACY_STATUS = os.environ.get("YOUTUBE_PUBLISH_PRIVACY_STATUS", "unlisted")


def _parse_video_id(url: str) -> str:
    for pattern in _VIDEO_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not parse a YouTube video ID from URL: {url}")


class YouTubeProvider(OAuthProvider):
    def __init__(self) -> None:
        self._client_id = os.environ.get("YOUTUBE_OAUTH_CLIENT_ID", "")
        self._client_secret = os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET", "")
        self._redirect_base = os.environ.get("OAUTH_REDIRECT_BASE_URL", "")
        if not (self._client_id and self._client_secret and self._redirect_base):
            raise RuntimeError(
                "YOUTUBE_OAUTH_CLIENT_ID, YOUTUBE_OAUTH_CLIENT_SECRET, and "
                "OAUTH_REDIRECT_BASE_URL must all be set"
            )

    @property
    def _redirect_uri(self) -> str:
        return f"{self._redirect_base}/api/social/youtube/callback"

    def get_authorize_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "access_type": "offline",  # required to receive a refresh_token
            "prompt": "consent",       # forces a refresh_token even on repeat connects
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenResult:
        resp = httpx.post(_TOKEN_URL, data={
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        account_id, username = self._fetch_channel_identity(data["access_token"])
        return TokenResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in_seconds=data.get("expires_in"),
            platform_account_id=account_id,
            platform_username=username,
        )

    def refresh_access_token(self, refresh_token: str) -> TokenResult:
        resp = httpx.post(_TOKEN_URL, data={
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "refresh_token",
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Google does not reissue a refresh_token on refresh — the caller keeps the existing one.
        return TokenResult(
            access_token=data["access_token"],
            refresh_token=None,
            expires_in_seconds=data.get("expires_in"),
        )

    def _fetch_channel_identity(self, access_token: str) -> tuple[Optional[str], Optional[str]]:
        resp = httpx.get(
            f"{_API_BASE}/channels",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"part": "snippet", "mine": "true"},
            timeout=20,
        )
        resp.raise_for_status()
        items = resp.json().get("items") or []
        if not items:
            return None, None
        return items[0]["id"], items[0]["snippet"].get("title")

    def fetch_post_metrics(self, access_token: str, post_url: str) -> PostMetrics:
        video_id = _parse_video_id(post_url)
        resp = httpx.get(
            f"{_API_BASE}/videos",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"part": "statistics", "id": video_id},
            timeout=20,
        )
        resp.raise_for_status()
        items = resp.json().get("items") or []
        if not items:
            raise RuntimeError(f"YouTube returned no video for id {video_id}")
        stats = items[0]["statistics"]
        return PostMetrics(
            platform_post_id=video_id,
            views=int(stats["viewCount"]) if "viewCount" in stats else None,
            likes=int(stats["likeCount"]) if "likeCount" in stats else None,
            comments=int(stats["commentCount"]) if "commentCount" in stats else None,
            shares=None,  # YouTube's public Data API has no share-count field
        )

    def publish(self, access_token: str, video_bytes: bytes, title: str, description: str) -> PostMetrics:
        # Single-shot multipart upload (not the chunked resumable protocol) —
        # simpler, and sufficient for this pipeline's short-form video sizes.
        boundary = "culturix_upload_boundary"
        metadata = json.dumps({
            "snippet": {"title": title[:100], "description": description[:5000], "categoryId": "22"},
            "status": {
                "privacyStatus": _DEFAULT_PRIVACY_STATUS,
                "selfDeclaredMadeForKids": False,
                # Every video this codebase publishes is Kling-generated —
                # always disclose, never conditional. YouTube added this
                # self-certification field specifically for realistic
                # altered/synthetic content; defaulting to True is the safe
                # choice given Kling's output can be realistic depending on
                # the prompt, and there's no reliable way to detect
                # "realistic enough to need it" automatically.
                "containsSyntheticMedia": True,
            },
        })
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: video/mp4\r\n\r\n"
        ).encode() + video_bytes + f"\r\n--{boundary}--".encode()

        resp = httpx.post(
            _UPLOAD_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            params={"uploadType": "multipart", "part": "snippet,status"},
            content=body,
            timeout=180,
        )
        resp.raise_for_status()
        video_id = resp.json()["id"]
        return PostMetrics(platform_post_id=video_id, views=0, likes=0, comments=0, shares=None)

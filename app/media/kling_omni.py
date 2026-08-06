"""Kling 3.0 Omni provider — character-consistent, multi-shot, voice-bound
video generation for CultureToons. This is a DIFFERENT API surface from the
existing `KlingProvider` in app/media/video.py (used by Shopify's product
reels): different base URL, different endpoints entirely. Deliberately NOT
reusing or modifying that class — Shopify's working reel generation stays
untouched; this is a standalone provider.

Auth: initially assumed the v3 docs' "Authorization: Bearer {apikey}" meant
a distinct, separately-issued static API key. Confirmed otherwise by
checking Kling's actual developer dashboard live — it only ever issues one
credential type (an Access Key + Secret Key pair, the same one video.py's
KlingProvider already uses, with a "JWT Verification" tool right next to
it), no separate key-issuance flow for a different credential type exists
anywhere on that page. So this uses the exact same JWT-Bearer mechanism as
the old provider (HS256, iss/exp/nbf claims), built from the SAME
KLING_ACCESS_KEY/KLING_SECRET_KEY already configured for Shopify reels — no
new credential needed. _make_jwt is duplicated from video.py (not imported),
matching this module's existing "keep the two providers independent" design.

Endpoint/parameter shapes below are transcribed directly from Kling's own
API documentation (Element Management, Voice Management, Omni Video
Generation pages), not inferred or guessed.
"""
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger("culturix.media.kling_omni")

_BASE = "https://api-singapore.klingai.com"
_ELEMENT_POLL_INTERVAL = 5
_ELEMENT_MAX_POLLS = 24        # ~2 min — element/voice registration is a lighter async task than video generation
_OMNI_POLL_INTERVAL = 10
_OMNI_MAX_POLLS = 60           # ~10 min — multi-shot generation up to 15s is heavier than a single 5s clip
_MAX_RATE_LIMIT_RETRIES = 4
_RATE_LIMIT_BACKOFF_SECONDS = 15  # doubles each retry: 15, 30, 60, 120


class KlingOmniError(Exception):
    pass


def _request_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    """Duplicated from video.py's _post_with_retry (not imported) — see this
    module's docstring for why the two Kling providers are kept independent.
    Handles Kling's account-level rate limit (429) with backoff."""
    for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
        resp = httpx.request(method, url, **kwargs)
        if resp.status_code != 429 or attempt == _MAX_RATE_LIMIT_RETRIES:
            return resp
        wait = int(resp.headers.get("Retry-After", _RATE_LIMIT_BACKOFF_SECONDS * (2 ** attempt)))
        time.sleep(wait)
    return resp


def _make_jwt(access_key: str, secret_key: str) -> str:
    """Duplicated from video.py's _make_jwt — see this module's docstring."""
    try:
        import jwt as pyjwt
    except ImportError:
        raise RuntimeError("PyJWT not installed — add 'PyJWT' to requirements.txt")
    now = int(time.time())
    payload = {"iss": access_key, "exp": now + 1800, "nbf": now - 5}
    return pyjwt.encode(payload, secret_key, algorithm="HS256")


class KlingOmniProvider:
    def __init__(self) -> None:
        self._access_key = os.getenv("KLING_ACCESS_KEY", "")
        self._secret_key = os.getenv("KLING_SECRET_KEY", "")
        if not self._access_key or not self._secret_key:
            raise RuntimeError("KLING_ACCESS_KEY and KLING_SECRET_KEY must be set")

    def _headers(self) -> dict:
        # Generated fresh per call (cheap, local — no network round trip)
        # rather than cached, since a single generation can involve several
        # slow polling loops that could plausibly outlive one token's 30-min
        # expiry if it were reused across the whole request lifecycle.
        token = _make_jwt(self._access_key, self._secret_key)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _check(self, resp: httpx.Response, context: str) -> dict:
        # A bare resp.raise_for_status() discards Kling's actual response
        # body on an HTTP error — confirmed live: a real 400 from
        # create_element surfaced only "400 Bad Request" with zero
        # indication of which field/constraint was actually violated, making
        # it undiagnosable without reproducing the exact same call. Kling's
        # error responses put the real reason in the JSON body (or plain
        # text), so read that before raising.
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise KlingOmniError(f"{context}: HTTP {resp.status_code} — {detail}")
        data = resp.json()
        if data.get("code", 0) != 0:
            raise KlingOmniError(f"{context}: {data.get('message', data)}")
        return data

    # ── Element registration ────────────────────────────────────────────

    def create_element(self, element_name: str, element_description: str, frontal_image_url: str,
                        refer_image_urls: Optional[list] = None, voice_id: Optional[str] = None,
                        tag_id: str = "o_102") -> str:
        """POST /v1/general/advanced-custom-elements (image_refer), poll
        GET .../{task_id}. Returns element_id."""
        body = {
            "element_name": element_name[:20],
            "element_description": element_description[:100],
            "reference_type": "image_refer",
            "element_image_list": {
                "frontal_image": frontal_image_url,
                "refer_images": [{"image_url": u} for u in (refer_image_urls or [])],
            },
            "tag_list": [{"tag_id": tag_id}],
        }
        if voice_id:
            body["element_voice_id"] = voice_id

        resp = _request_with_retry("POST", f"{_BASE}/v1/general/advanced-custom-elements",
                                    headers=self._headers(), json=body, timeout=30)
        data = self._check(resp, "Kling create_element")
        task_id = data["data"]["task_id"]

        for _ in range(_ELEMENT_MAX_POLLS):
            time.sleep(_ELEMENT_POLL_INTERVAL)
            poll = httpx.get(f"{_BASE}/v1/general/advanced-custom-elements/{task_id}",
                              headers=self._headers(), timeout=20)
            pdata = self._check(poll, "Kling create_element poll")["data"]
            status = pdata.get("task_status", "")
            if status == "succeed":
                elements = pdata.get("task_result", {}).get("elements") or []
                if not elements:
                    raise KlingOmniError(f"Kling create_element succeeded but returned no elements: {pdata}")
                return str(elements[0]["element_id"])
            if status == "failed":
                raise KlingOmniError(f"Kling create_element task failed: {pdata.get('task_status_msg')}")

        raise KlingOmniError(f"Kling create_element task {task_id} did not complete in time")

    # ── Voice ────────────────────────────────────────────────────────────

    def create_voice(self, voice_name: str, voice_url: str) -> str:
        """POST /v1/general/custom-voices, poll GET .../{task_id}. Returns voice_id."""
        body = {"voice_name": voice_name[:20], "voice_url": voice_url}
        resp = _request_with_retry("POST", f"{_BASE}/v1/general/custom-voices",
                                    headers=self._headers(), json=body, timeout=30)
        data = self._check(resp, "Kling create_voice")
        task_id = data["data"]["task_id"]

        for _ in range(_ELEMENT_MAX_POLLS):
            time.sleep(_ELEMENT_POLL_INTERVAL)
            poll = httpx.get(f"{_BASE}/v1/general/custom-voices/{task_id}",
                              headers=self._headers(), timeout=20)
            pdata = self._check(poll, "Kling create_voice poll")["data"]
            status = pdata.get("task_status", "")
            if status == "succeed":
                voices = pdata.get("task_result", {}).get("voices") or []
                if not voices:
                    raise KlingOmniError(f"Kling create_voice succeeded but returned no voices: {pdata}")
                return str(voices[0]["voice_id"])
            if status == "failed":
                raise KlingOmniError(f"Kling create_voice task failed: {pdata.get('task_status_msg')}")

        raise KlingOmniError(f"Kling create_voice task {task_id} did not complete in time")

    def list_preset_voices(self) -> list:
        """GET /v1/general/presets-voices — stock voices, for a character
        that doesn't need a cloned voice."""
        resp = httpx.get(f"{_BASE}/v1/general/presets-voices", headers=self._headers(),
                          params={"pageNum": 1, "pageSize": 100}, timeout=20)
        data = self._check(resp, "Kling list_preset_voices")
        voices = []
        for task in data.get("data") or []:
            voices.extend(task.get("task_result", {}).get("voices") or [])
        return voices

    # ── Omni video generation ────────────────────────────────────────────

    def generate_omni_video(self, contents: list, settings: dict, options: Optional[dict] = None) -> dict:
        """POST /omni-video/kling-3.0-omni, poll GET /tasks?task_ids={id}.
        `contents` is the full typed list (prompt/element/refer_image/etc, per
        Kling's Omni contract) — callers build this, not this method. Returns
        {"video_bytes": bytes, "duration_seconds": float, "task_id": str}."""
        body = {"contents": contents, "settings": settings}
        if options:
            body["options"] = options

        resp = _request_with_retry("POST", f"{_BASE}/omni-video/kling-3.0-omni",
                                    headers=self._headers(), json=body, timeout=30)
        data = self._check(resp, "Kling generate_omni_video")
        task_id = data["data"]["id"]

        for _ in range(_OMNI_MAX_POLLS):
            time.sleep(_OMNI_POLL_INTERVAL)
            poll = httpx.get(f"{_BASE}/tasks", headers=self._headers(),
                              params={"task_ids": task_id}, timeout=20)
            pdata_list = self._check(poll, "Kling generate_omni_video poll")["data"]
            if not pdata_list:
                continue
            pdata = pdata_list[0]
            status = pdata.get("status", "")
            if status == "succeeded":
                outputs = pdata.get("outputs") or []
                video_output = next((o for o in outputs if o.get("type") == "video"), None)
                if not video_output or not video_output.get("url"):
                    raise KlingOmniError(f"Kling omni task succeeded but no video output: {pdata}")
                video_resp = httpx.get(video_output["url"], timeout=120)
                video_resp.raise_for_status()
                return {
                    "video_bytes": video_resp.content,
                    "duration_seconds": float(video_output.get("duration") or settings.get("duration", 0)),
                    "task_id": task_id,
                }
            if status == "failed":
                raise KlingOmniError(f"Kling omni task failed: {pdata.get('message')}")

        raise KlingOmniError(f"Kling omni task {task_id} did not complete in time")

"""OneSignal Web Push — notifies a user that their staged content is ready
to 1-click launch (see app/social/service.py's stage_and_notify()).

Requires ONESIGNAL_APP_ID and ONESIGNAL_REST_API_KEY. When either is unset
this soft-fails (returns {"ok": False, ...}) rather than raising, mirroring
app/billing.py's pattern for optional integrations — a staging job must
never fail just because push isn't configured yet; the ContentPost row is
already persisted and visible in-app regardless.

Targets the user by the external_id alias, set client-side via
OneSignal.login(userId) (see culturix-web/src/lib/onesignal.ts) when the
user opts into notifications. Verify "include_aliases" is still the current
REST field name against OneSignal's docs before relying on this in
production — their v1 -> v16 SDK migration renamed some targeting fields
(the older equivalent was "include_external_user_ids"), and it's the one
part of this module actually calling out to a third party.
"""
import logging
import os

import httpx

logger = logging.getLogger("culturix.notifications")

_ONESIGNAL_API_URL = "https://onesignal.com/api/v1/notifications"


def send_stage_ready_push(user_id: str, post_id: str, video_url: str,
                           caption_text: str, target_platform: str) -> dict:
    app_id = os.getenv("ONESIGNAL_APP_ID")
    api_key = os.getenv("ONESIGNAL_REST_API_KEY")
    if not app_id or not api_key:
        logger.warning("OneSignal not configured — skipping push for post %s", post_id)
        return {"ok": False, "reason": "onesignal_not_configured"}

    site_url = os.getenv("NEXT_PUBLIC_SITE_URL", "https://culturixcloud.com").rstrip("/")
    landing_url = f"{site_url}/publish/{post_id}"

    try:
        resp = httpx.post(
            _ONESIGNAL_API_URL,
            headers={"Authorization": f"Basic {api_key}", "Content-Type": "application/json"},
            json={
                "app_id": app_id,
                "include_aliases": {"external_id": [user_id]},
                "target_channel": "push",
                "headings": {"en": "Your content is ready to post"},
                "contents": {
                    "en": f"Tap to launch on {target_platform.title()} — video's rendered, "
                          f"caption's written, ready to go."
                },
                "url": landing_url,
                "data": {
                    "post_id": post_id,
                    "video_url": video_url,
                    "caption_text": caption_text,
                    "target_platform": target_platform,
                },
            },
            timeout=15,
        )
        resp.raise_for_status()
        return {"ok": True, "onesignal_id": resp.json().get("id")}
    except Exception as exc:
        logger.error("OneSignal push failed for post %s: %s", post_id, exc)
        return {"ok": False, "reason": str(exc)[:300]}

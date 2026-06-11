"""Supabase Storage upload helper.

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.
Bucket "media" must exist in your Supabase project with public read access.
Create it once via: Supabase dashboard → Storage → New bucket → name "media", Public ON.
"""
import os
import httpx

_BUCKET = "media"


def upload(data: bytes, path: str, content_type: str) -> str:
    """Upload bytes to Supabase Storage. Returns the public URL."""
    url_base = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url_base or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    upload_url = f"{url_base}/storage/v1/object/{_BUCKET}/{path}"
    resp = httpx.post(
        upload_url,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": content_type,
        },
        content=data,
        timeout=120,
    )
    if resp.status_code == 409:
        # Already exists — upsert via PUT
        resp = httpx.put(
            upload_url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": content_type,
            },
            content=data,
            timeout=120,
        )
    resp.raise_for_status()
    return f"{url_base}/storage/v1/object/public/{_BUCKET}/{path}"

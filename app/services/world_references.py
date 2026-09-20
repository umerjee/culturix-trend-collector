"""Real reference photos as the opening frame of each scene in a World video.

The video model starts each segment from a first-frame image. With nothing to
show it uses a dark neutral canvas, which (a) makes every segment fade in from
black and (b) leaves the model to invent what a landing craft, a battleship or
an obstacle looks like. A real photograph of the actual thing fixes both.

Only PUBLIC-DOMAIN images are used (Wikimedia Commons, filtered on the license
recorded there: US government and expired-Crown-copyright archive photos, for
example). Anything else is rejected rather than trusted, because the frame is
conditioning input to a video we publish. Images are copied into our own
storage: the renderer fetches them by URL, and Wikimedia rejects requests
without a descriptive User-Agent.
"""
import logging
import uuid
from typing import Optional

import httpx

logger = logging.getLogger("culturix.services.world_references")

_API = "https://commons.wikimedia.org/w/api.php"
_HEADERS = {"User-Agent": "culturix-trend-collector/1.0 (contact: umer.ali79@gmail.com)"}
MIN_WIDTH = 900
_ALLOWED_MIME = ("image/jpeg", "image/png")


class ReferenceError(Exception):
    pass


def is_public_domain(license_name: str, usage_terms: str = "") -> bool:
    """True only when Commons records the file as public domain. Creative Commons,
    GFDL and unknown licenses are all rejected."""
    text = f"{license_name} {usage_terms}".lower()
    if any(bad in text for bad in ("cc by", "cc-by", "cc0", "gfdl", "attribution", "share alike", "sharealike")):
        return False
    return "public domain" in text or text.strip().startswith(("pd-", "pd "))


def find_public_domain_images(query: str, limit: int = 8, min_width: int = MIN_WIDTH) -> list[dict]:
    """Public-domain photos matching `query`, best match first: [{title, page, url (1280px),
    width, height, license, credit, description}]. [] on any failure — never raises."""
    try:
        search = httpx.get(_API, params={"action": "query", "list": "search", "srsearch": query, "srnamespace": 6,
                                         "srlimit": max(limit * 3, 10), "format": "json"},
                           headers=_HEADERS, timeout=20.0)
        search.raise_for_status()
        titles = [h["title"] for h in search.json()["query"]["search"]]
        if not titles:
            return []
        found = []
        for i in range(0, len(titles), 20):
            info = httpx.get(_API, params={"action": "query", "titles": "|".join(titles[i:i + 20]), "prop": "imageinfo",
                                           "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280, "format": "json"},
                             headers=_HEADERS, timeout=20.0)
            info.raise_for_status()
            found += list(info.json()["query"]["pages"].values())
    except Exception as exc:
        logger.warning("Reference image search failed for %r: %s", query, exc)
        return []

    order = {t: n for n, t in enumerate(titles)}
    results = []
    for page in found:
        ii = (page.get("imageinfo") or [None])[0]
        if not ii or ii.get("mime") not in _ALLOWED_MIME or (ii.get("width") or 0) < min_width:
            continue
        meta = ii.get("extmetadata", {})
        license_name = (meta.get("LicenseShortName") or {}).get("value", "")
        terms = (meta.get("UsageTerms") or {}).get("value", "")
        if not is_public_domain(license_name, terms) or not ii.get("thumburl"):
            continue
        results.append({
            "title": page["title"], "page": ii.get("descriptionurl"), "url": ii["thumburl"],
            "width": ii["width"], "height": ii["height"], "license": license_name,
            "credit": _plain((meta.get("Credit") or {}).get("value", "") or (meta.get("Artist") or {}).get("value", "")),
            "description": _plain((meta.get("ImageDescription") or {}).get("value", ""))[:200],
            "_order": order.get(page["title"], 999),
        })
    results.sort(key=lambda r: r.pop("_order"))
    return results[:limit]


def _plain(html: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def fetch_image(url: str) -> bytes:
    resp = httpx.get(url, headers=_HEADERS, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    if not resp.content:
        raise ReferenceError(f"Empty image from {url}")
    return resp.content


def store_scene_reference(session, brand, *, name: str, description: str, country: Optional[str],
                          image_bytes: bytes, content_type: str = "image/jpeg"):
    """Copy a reference photo into our storage and record it as a Location (ToonBackground)
    for the brand. Returns the ToonBackground."""
    from app.media import storage
    from app.models.toon_background import ToonBackground

    ext = "png" if content_type == "image/png" else "jpg"
    url = storage.upload(image_bytes, f"world/references/{brand.id}/{uuid.uuid4().hex[:12]}.{ext}", content_type)
    row = ToonBackground(brand_id=brand.id, name=name[:120], image_url=url, description=description,
                         country=(country or None), tags="world,reference")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row

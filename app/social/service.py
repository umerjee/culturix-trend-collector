"""Social-platform service — orchestrates OAuth provider + token refresh + DB
updates for both the manual-tracking and publish flows. Mirrors
app/media/service.py's shape (provider registry, background-task functions
that load a row, do the work, write the result back)."""
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger("culturix.social")

_PROVIDERS = {
    "youtube": ("app.social.youtube", "YouTubeProvider"),
}


def _get_provider(platform: str):
    module_path, class_name = _PROVIDERS[platform]
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)()


def resolve_active_account(session, user_id, platform: str, content_profile_id=None):
    """Resolves which ConnectedAccount a post/publish/fetch should use for a
    given user+platform. Prefers the account dedicated to content_profile_id
    (a user's own "avatar account" for that niche, see ConnectedAccount's
    content_profile_id) and falls back to the legacy user-wide account
    (content_profile_id IS NULL) so any existing single-account user sees
    zero behavior change. Used by both the /api/content-posts* route
    pre-flight checks and the actual background fetch/publish tasks below,
    so the two never disagree about which account is in play."""
    from app.models.connected_account import ConnectedAccount

    if content_profile_id is not None:
        account = session.query(ConnectedAccount).filter_by(
            content_profile_id=content_profile_id, platform=platform, status="active"
        ).first()
        if account:
            return account

    return session.query(ConnectedAccount).filter_by(
        user_id=user_id, platform=platform, content_profile_id=None, status="active"
    ).first()


def _get_valid_access_token(session, connected_account) -> str:
    from app.social.crypto import decrypt, encrypt

    now = datetime.utcnow()
    if connected_account.token_expires_at and connected_account.token_expires_at <= now:
        provider = _get_provider(connected_account.platform)
        refresh_token = decrypt(connected_account.refresh_token) if connected_account.refresh_token else None
        if not refresh_token:
            connected_account.status = "needs_reconnect"
            session.commit()
            raise RuntimeError(
                f"{connected_account.platform} token expired and no refresh_token available — reconnect required"
            )
        try:
            result = provider.refresh_access_token(refresh_token)
        except Exception:
            connected_account.status = "error"
            session.commit()
            raise
        connected_account.access_token = encrypt(result.access_token)
        if result.expires_in_seconds:
            connected_account.token_expires_at = now + timedelta(seconds=result.expires_in_seconds)
        connected_account.last_refreshed_at = now
        connected_account.status = "active"
        session.commit()
        return result.access_token

    return decrypt(connected_account.access_token)


def fetch_and_record(content_post_id: str) -> None:
    """Background task for manual tracking — fetches current metrics for an
    already-created ContentPost row and writes a snapshot."""
    from app.db import SessionLocal
    from app.models.content_post import ContentPost
    from app.models.content_post_snapshot import ContentPostSnapshot
    from app.models.generated_content import GeneratedContent
    import uuid as _uuid

    session = SessionLocal()
    try:
        post = session.query(ContentPost).filter_by(id=_uuid.UUID(content_post_id)).first()
        if not post:
            return
        post.status = "fetching"
        session.commit()

        content = session.query(GeneratedContent).filter_by(id=post.generated_content_id).first()
        account = resolve_active_account(
            session, post.user_id, post.platform,
            content_profile_id=content.content_profile_id if content else None,
        )
        if not account:
            post.status = "needs_reconnect"
            post.error = f"No active {post.platform} connection"
            session.commit()
            return

        access_token = _get_valid_access_token(session, account)
        provider = _get_provider(post.platform)
        metrics = provider.fetch_post_metrics(access_token, post.post_url)

        session.add(ContentPostSnapshot(
            content_post_id=post.id,
            captured_at=datetime.utcnow(),
            views=metrics.views, likes=metrics.likes,
            comments=metrics.comments, shares=metrics.shares,
        ))
        post.platform_post_id = metrics.platform_post_id
        post.latest_views = metrics.views
        post.latest_likes = metrics.likes
        post.latest_comments = metrics.comments
        post.latest_shares = metrics.shares
        post.last_fetched_at = datetime.utcnow()
        post.status = "tracked"
        post.error = None
        session.commit()

    except Exception as exc:
        logger.error("fetch_and_record failed for %s: %s", content_post_id, exc)
        try:
            post = session.query(ContentPost).filter_by(id=_uuid.UUID(content_post_id)).first()
            if post:
                post.status = "failed"
                post.error = str(exc)
                session.commit()
        except Exception:
            pass
    finally:
        session.close()


def publish_and_record(content_post_id: str) -> None:
    """Background task for one-click / autonomous publish — loads an already-
    created (status='pending') ContentPost row, publishes the idea's finished
    video via the platform's API, and fills in the row from the result."""
    from app.db import SessionLocal
    from app.models.content_post import ContentPost
    from app.models.content_post_snapshot import ContentPostSnapshot
    from app.models.generated_media import GeneratedMedia
    from app.models.generated_content import GeneratedContent
    import uuid as _uuid

    session = SessionLocal()
    try:
        post = session.query(ContentPost).filter_by(id=_uuid.UUID(content_post_id)).first()
        if not post:
            return

        content = session.query(GeneratedContent).filter_by(id=post.generated_content_id).first()
        account = resolve_active_account(
            session, post.user_id, post.platform,
            content_profile_id=content.content_profile_id if content else None,
        )
        if not account:
            post.status = "needs_reconnect"
            post.error = f"No active {post.platform} connection"
            session.commit()
            return

        media = (
            session.query(GeneratedMedia)
            .filter_by(generated_content_id=post.generated_content_id, idea_index=post.idea_index,
                       media_type="video", status="done")
            .order_by(GeneratedMedia.created_at.desc())
            .first()
        )
        if not media or not media.asset_url:
            post.status = "failed"
            post.error = "No finished video found for this idea — generate one first"
            session.commit()
            return

        idea = (content.content_ideas or [])[post.idea_index] if content else {}
        title = (idea.get("hook") or "Culturix post")[:100]
        description = "\n\n".join(filter(None, [idea.get("caption"), idea.get("hashtag_strategy")]))

        video_resp = httpx.get(media.asset_url, timeout=120)
        video_resp.raise_for_status()

        access_token = _get_valid_access_token(session, account)
        provider = _get_provider(post.platform)
        metrics = provider.publish(access_token, video_resp.content, title, description)

        post.platform_post_id = metrics.platform_post_id
        post.post_url = _post_url(post.platform, metrics.platform_post_id)
        post.latest_views = metrics.views or 0
        post.latest_likes = metrics.likes or 0
        post.latest_comments = metrics.comments or 0
        post.latest_shares = metrics.shares
        post.last_fetched_at = datetime.utcnow()
        post.posted_at = datetime.utcnow()
        post.tracking_until = datetime.utcnow() + timedelta(days=14)
        post.status = "tracked"
        post.error = None
        session.add(ContentPostSnapshot(
            content_post_id=post.id, captured_at=datetime.utcnow(),
            views=post.latest_views, likes=post.latest_likes,
            comments=post.latest_comments, shares=post.latest_shares,
        ))
        session.commit()

    except Exception as exc:
        logger.error("publish_and_record failed for %s: %s", content_post_id, exc)
        try:
            post = session.query(ContentPost).filter_by(id=_uuid.UUID(content_post_id)).first()
            if post:
                post.status = "failed"
                post.error = str(exc)
                session.commit()
        except Exception:
            pass
    finally:
        session.close()


def _post_url(platform: str, platform_post_id: Optional[str]) -> Optional[str]:
    if not platform_post_id:
        return None
    if platform == "youtube":
        return f"https://www.youtube.com/watch?v={platform_post_id}"
    return None

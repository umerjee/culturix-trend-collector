"""Periodic health checks for this codebase's two unofficial/no-SLA
integrations — edge-tts (unofficial Microsoft Edge TTS client, app/media/
voice.py) and the Twitter proxy (Jina-wrapped trends24.in scrape,
app/collectors/twitter.py's fallback path). Both have no guaranteed uptime
and can silently break on an upstream change; this makes that visible
instead of only surfacing as a downstream failure days later.
"""
import logging

logger = logging.getLogger("culturix.integration_health")


def check_edge_tts() -> tuple[str, str | None]:
    try:
        from app.media.voice import EdgeTTSProvider
        result = EdgeTTSProvider().synthesize("health check")
        if not result.asset_bytes:
            return "unhealthy", "synthesize() returned no audio bytes"
        return "healthy", None
    except Exception as e:
        return "unhealthy", str(e)[:500]


def check_twitter_proxy() -> tuple[str, str | None]:
    try:
        import httpx
        from app.collectors.twitter import JINA_PROXY

        resp = httpx.get(JINA_PROXY.format(region="US"), timeout=20.0)
        if resp.status_code != 200:
            return "unhealthy", f"HTTP {resp.status_code}"
        if not resp.text.strip():
            return "unhealthy", "empty response body"
        return "healthy", None
    except Exception as e:
        return "unhealthy", str(e)[:500]


_CHECKS = {
    "edge_tts": check_edge_tts,
    "twitter_proxy": check_twitter_proxy,
}


def run_all_health_checks() -> dict:
    from datetime import datetime
    from app.db import SessionLocal
    from app.models.integration_health import IntegrationHealth

    session = SessionLocal()
    results = {}
    try:
        for name, check_fn in _CHECKS.items():
            status, error = check_fn()
            results[name] = status
            if status != "healthy":
                logger.warning("Integration unhealthy: %s — %s", name, error)
            session.add(IntegrationHealth(
                integration_name=name, status=status, error=error,
                checked_at=datetime.utcnow(),
            ))
        session.commit()
    finally:
        session.close()
    return results

"""
Content Check — daily relevance audit for previously generated content ideas.

Scores each idea (inside GeneratedContent.content_ideas) on:
  - trend relevance (50%) — is the trend it's built on still showing up in recent signals?
  - platform freshness (30%) — is this angle still fresh, or oversaturated?
  - persona fit (20%) — has the owning content profile changed since generation?

Marks each idea live/aging/stale(->retired) in place and logs the audit to
content_check_log. Unlike a from-scratch design, there's no per-idea on-demand
regeneration here — retiring an idea just deprioritizes it on the dashboard;
the next day's normal generate_content run supplies fresh ideas.

Usage:
    python -m app.pipeline.nodes.content_check
"""
import json
import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger("culturix.pipeline.content_check")

RECENT_SIGNAL_HOURS = 4
AUDIT_WINDOW_DAYS = 30
MAX_REFRESH_COUNT = 2


def _get_llm_client():
    """DeepSeek first, falls back to Claude Haiku — mirrors clusterer.py's pattern."""
    if os.getenv("DEEPSEEK_API_KEY"):
        from openai import OpenAI
        return "deepseek", OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")
    import anthropic
    return "claude", anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _score_via_llm(prompt: str) -> dict:
    try:
        kind, client = _get_llm_client()
        if kind == "deepseek":
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            raw = response.choices[0].message.content.strip()
        else:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        logger.warning("Relevance scoring call failed, defaulting to neutral: %s", e)
        return {"score": 50, "reason": "scoring unavailable"}


def _score_trend_relevance(idea: dict, recent_texts: list) -> int:
    trend_connection = idea.get("trend_connection", "")
    if not trend_connection or not recent_texts:
        return 50

    prompt = f"""A piece of content was built around this trend: "{trend_connection}"

Here are {len(recent_texts)} recent social media posts from the last {RECENT_SIGNAL_HOURS} hours:
{json.dumps(recent_texts[:50], ensure_ascii=False)}

On a scale of 0-100, how relevant is this trend still?
- 90-100: trend is exploding right now
- 70-89: trend is still active
- 40-69: trend is fading
- 0-39: trend has died or been replaced

Return ONLY a JSON object: {{"score": <number>, "reason": "<one sentence>"}}"""
    return _score_via_llm(prompt).get("score", 50)


def _score_platform_freshness(idea: dict, recent_texts: list) -> int:
    hook = idea.get("hook", "")
    platform = idea.get("platform", "")
    if not hook or not recent_texts:
        return 50

    prompt = f"""Content hook: "{hook}"
Platform: {platform}

Recent posts on this platform (last {RECENT_SIGNAL_HOURS} hours):
{json.dumps(recent_texts[:30], ensure_ascii=False)}

On a scale of 0-100, how fresh is this content angle?
- 90-100: this angle is unique right now
- 70-89: some similar content but not oversaturated
- 40-69: this angle is getting common
- 0-39: this exact type of content is everywhere right now

Return ONLY a JSON object: {{"score": <number>, "reason": "<one sentence>"}}"""
    return _score_via_llm(prompt).get("score", 50)


def _score_persona_fit(generated_at, profile_updated_at) -> int:
    """No AI call — if the owning content profile changed after this content was
    generated, the content may no longer match current targeting."""
    if generated_at and profile_updated_at and profile_updated_at > generated_at:
        return 60
    return 90


def _determine_status(score: int) -> str:
    if score >= 80:
        return "live"
    elif score >= 50:
        return "aging"
    return "stale"


def run_content_check() -> dict:
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.models.generated_content import GeneratedContent
    from app.models.content_profile import ContentProfile
    from app.models.content_check_log import ContentCheckLog
    from sqlalchemy.orm.attributes import flag_modified

    logger.info("Content Check starting — %s", datetime.utcnow().isoformat())

    session = SessionLocal()
    try:
        recent_cutoff = datetime.utcnow() - timedelta(hours=RECENT_SIGNAL_HOURS)
        recent_rows = (
            session.query(Trend.translated_content)
            .filter(Trend.collected_at >= recent_cutoff)
            .filter(Trend.translated_content.isnot(None))
            .limit(200)
            .all()
        )
        recent_texts = [r[0] for r in recent_rows if r[0]]

        audit_cutoff = datetime.utcnow() - timedelta(days=AUDIT_WINDOW_DAYS)
        contents = (
            session.query(GeneratedContent)
            .filter(GeneratedContent.generated_at >= audit_cutoff)
            .all()
        )

        profile_updated_at_cache: dict = {}
        audited = 0
        retired = 0

        for content in contents:
            ideas = content.content_ideas or []
            if not ideas:
                continue

            profile_id = content.content_profile_id
            if profile_id and profile_id not in profile_updated_at_cache:
                profile = session.query(ContentProfile).filter_by(id=profile_id).first()
                profile_updated_at_cache[profile_id] = profile.updated_at if profile else None
            p_updated_at = profile_updated_at_cache.get(profile_id)

            changed = False
            for idx, idea in enumerate(ideas):
                if idea.get("status") == "retired":
                    continue

                prev_status = idea.get("status", "live")
                prev_score = idea.get("relevance_score", 100)

                trend_score = _score_trend_relevance(idea, recent_texts)
                freshness_score = _score_platform_freshness(idea, recent_texts)
                persona_score = _score_persona_fit(content.generated_at, p_updated_at)
                new_score = int(trend_score * 0.5 + freshness_score * 0.3 + persona_score * 0.2)
                new_status = _determine_status(new_score)

                if new_status == "stale":
                    action = "retired"
                    final_status = "retired"
                    idea["refresh_count"] = min(idea.get("refresh_count", 0) + 1, MAX_REFRESH_COUNT)
                elif new_status == "aging" and prev_status == "live":
                    action = "flagged"
                    final_status = "aging"
                else:
                    action = "kept"
                    final_status = new_status

                idea["status"] = final_status
                idea["relevance_score"] = new_score
                idea["last_checked_at"] = datetime.utcnow().isoformat()
                changed = True

                session.add(ContentCheckLog(
                    generated_content_id=content.id,
                    idea_index=idx,
                    previous_score=prev_score,
                    new_score=new_score,
                    trend_score=trend_score,
                    freshness_score=freshness_score,
                    persona_score=persona_score,
                    previous_status=prev_status,
                    new_status=final_status,
                    action_taken=action,
                ))
                audited += 1
                if final_status == "retired":
                    retired += 1

            if changed:
                flag_modified(content, "content_ideas")

        session.commit()
        logger.info("Content Check complete. Audited: %d, Retired: %d", audited, retired)
        return {"audited": audited, "retired": retired, "digests_checked": len(contents)}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_content_check())

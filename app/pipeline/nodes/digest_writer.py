"""
Digest Writer — persists generated content to DB and dispatches email digests via Resend.
"""
import json
import logging
import os
from datetime import date
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.digest_writer")


def _save_to_db(user_id: str, clusters: list[dict], ideas: list[dict]) -> str:
    from app.db import SessionLocal
    import sqlalchemy as sa

    session = SessionLocal()
    try:
        result = session.execute(
            sa.text("""
                INSERT INTO generated_content (user_id, trend_date, clusters, content_ideas, delivered)
                VALUES (:user_id, :trend_date, :clusters, :ideas, FALSE)
                RETURNING id
            """),
            {
                "user_id": user_id,
                "trend_date": date.today().isoformat(),
                "clusters": json.dumps(clusters),
                "ideas": json.dumps(ideas),
            },
        )
        row = result.fetchone()
        session.commit()
        return str(row[0]) if row else ""
    except Exception as e:
        session.rollback()
        logger.error("DB write failed for user %s: %s", user_id, e)
        return ""
    finally:
        session.close()


def _get_user_email(user_id: str) -> str | None:
    from app.db import SessionLocal
    import sqlalchemy as sa

    session = SessionLocal()
    try:
        result = session.execute(
            sa.text("SELECT email FROM users WHERE id = :uid LIMIT 1"),
            {"uid": user_id},
        )
        row = result.fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        session.close()


def _render_email(ideas: list[dict], clusters: list[dict]) -> str:
    today = date.today().strftime("%B %d, %Y")
    idea_html = ""
    for i, idea in enumerate(ideas[:10], 1):
        idea_html += f"""
        <div style="border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:12px;">
          <p style="font-size:11px;color:#9ca3af;margin:0 0 6px">#{i:02d} · {idea.get('platform','')} · {idea.get('format','')}</p>
          <p style="font-size:16px;font-weight:700;color:#111827;margin:0 0 8px">{idea.get('hook','')}</p>
          <p style="font-size:13px;color:#6b7280;margin:0 0 8px">{idea.get('caption','')}</p>
          <p style="font-size:12px;color:#2563eb;margin:0 0 4px"><strong>CTA:</strong> {idea.get('cta','')}</p>
          <p style="font-size:12px;color:#7c3aed;margin:0"><strong>Music:</strong> {idea.get('music_mood','')}</p>
        </div>"""

    trend_html = "".join(
        f'<span style="background:#eff6ff;color:#1d4ed8;border-radius:20px;padding:4px 10px;font-size:12px;margin-right:6px">{c.get("name","")}</span>'
        for c in clusters[:5]
    )

    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;padding:24px">
      <div style="text-align:center;padding:24px 0 32px">
        <p style="font-size:24px;font-weight:800;color:#1e3a8a;margin:0">⚡ Culturix</p>
        <p style="color:#6b7280;margin:8px 0 0">{today}</p>
      </div>
      <div style="margin-bottom:24px">
        <h2 style="font-size:18px;font-weight:700;color:#111827;margin:0 0 12px">Today's cultural signals</h2>
        {trend_html}
      </div>
      <h2 style="font-size:18px;font-weight:700;color:#111827;margin:0 0 16px">Your 10 content ideas</h2>
      {idea_html}
      <div style="text-align:center;padding:24px 0;border-top:1px solid #f3f4f6;margin-top:24px">
        <a href="{os.getenv('NEXT_PUBLIC_SITE_URL','')}/dashboard"
           style="background:#2563eb;color:white;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;font-size:14px">
          View full dashboard
        </a>
        <p style="color:#9ca3af;font-size:12px;margin-top:16px">Culturix · Daily trend intelligence</p>
      </div>
    </div>"""


def _send_email(to: str, html: str):
    resend_key = os.getenv("RESEND_API_KEY")
    if not resend_key:
        logger.warning("RESEND_API_KEY not set — skipping email delivery")
        return

    try:
        import resend
        resend.api_key = resend_key
        resend.Emails.send({
            "from": "digest@culturix.ai",
            "to": to,
            "subject": f"Your Culturix Digest — {date.today().strftime('%B %d')}",
            "html": html,
        })
        logger.info("Email sent to %s", to)
    except Exception as e:
        logger.error("Email delivery failed to %s: %s", to, e)


def write_digests(state: PipelineState) -> PipelineState:
    content_list = state.get("generated_content", [])
    if not content_list:
        logger.warning("No generated content to write")
        return state

    for item in content_list:
        user_id = item["user_id"]
        ideas = item.get("ideas", [])
        clusters = item.get("clusters", [])

        # Save to DB
        digest_id = _save_to_db(user_id, clusters, ideas)
        if digest_id:
            logger.info("Saved digest %s for user %s", digest_id, user_id)

        # Send email
        email = _get_user_email(user_id)
        if email and ideas:
            html = _render_email(ideas, clusters)
            _send_email(email, html)

    logger.info("Digest writing complete for %d users", len(content_list))
    return state

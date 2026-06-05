from app.db import SessionLocal
from app.models.trend import Trend
from app.embeddings import embed_batch


def process_embeddings(limit: int = 500) -> int:
    session = SessionLocal()
    try:
        trends = (
            session.query(Trend)
            .filter(Trend.embedding.is_(None))
            .order_by(Trend.id.desc())
            .limit(limit)
            .all()
        )

        to_embed = [
            t for t in trends
            if (t.translated_content or t.content or "").strip()
        ]

        if not to_embed:
            return 0

        texts = [t.translated_content or t.content or "" for t in to_embed]
        embeddings = embed_batch(texts)

        for trend, embedding in zip(to_embed, embeddings):
            trend.embedding = embedding

        session.commit()
        return len(to_embed)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

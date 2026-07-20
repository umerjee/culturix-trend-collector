from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.trend_theme import TrendTheme
from app.models.trend_occurrence import TrendOccurrence
from app.pipeline.nodes.trend_historian import (
    _compute_recurrence,
    _cosine_similarity,
    _average_embedding,
    map_trend_history,
)


class TestComputeRecurrence:
    def test_fewer_than_three_occurrences_is_unclear(self):
        dates = [date(2026, 1, 1), date(2026, 1, 8)]
        assert _compute_recurrence(dates) == ("unclear", None, 0.0)

    def test_same_weekday_over_weeks_is_weekly(self):
        base = date(2026, 1, 2)  # Friday
        dates = [base + timedelta(weeks=i) for i in range(4)]
        pattern, dominant_day, confidence = _compute_recurrence(dates)
        assert pattern == "weekly"
        assert dominant_day == base.weekday()
        assert confidence == 1.0

    def test_recurring_around_same_calendar_window_across_years_is_yearly(self):
        dates = [
            date(2024, 3, 1), date(2024, 3, 3),
            date(2025, 3, 2), date(2025, 3, 4),
        ]
        pattern, dominant_day, confidence = _compute_recurrence(dates)
        assert pattern == "yearly"
        assert dominant_day is None
        assert confidence > 0

    def test_frequent_occurrences_with_no_dominant_weekday_is_sustained(self):
        base = date(2026, 2, 1)
        dates = [base + timedelta(days=i) for i in range(22)]
        pattern, dominant_day, _ = _compute_recurrence(dates)
        assert pattern == "sustained"
        assert dominant_day is None

    def test_tight_short_burst_is_spike(self):
        base = date(2026, 5, 1)
        dates = [base, base + timedelta(days=1), base + timedelta(days=2)]
        pattern, dominant_day, confidence = _compute_recurrence(dates)
        assert pattern == "spike"
        assert dominant_day is None
        assert confidence == 0.5


class TestCosineSimilarity:
    def test_identical_vectors_are_maximally_similar(self):
        assert _cosine_similarity([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)

    def test_orthogonal_vectors_are_zero(self):
        assert _cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_mismatched_or_empty_vectors_return_zero(self):
        assert _cosine_similarity([], [1, 2]) == 0.0
        assert _cosine_similarity([1, 2], [1, 2, 3]) == 0.0


class TestAverageEmbedding:
    def test_no_prior_centroid_returns_new_vector_unchanged(self):
        assert _average_embedding([], [1, 2], 0) == [1, 2]

    def test_weighted_average_accounts_for_prior_occurrence_count(self):
        assert _average_embedding([0, 0], [2, 2], 1) == [1.0, 1.0]


@pytest.fixture
def historian_db(mocker):
    """In-memory SQLite standing in for the app's Postgres DB — real ORM
    behavior (matching, idempotency) without hand-mocking query chains."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[TrendTheme.__table__, TrendOccurrence.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestMapTrendHistory:
    def test_empty_clusters_short_circuits_without_embedding(self, mocker):
        mock_embed = mocker.patch("app.embeddings.embed_batch")
        state = {"clusters": []}

        result = map_trend_history(state)

        assert result["clusters"] == []
        mock_embed.assert_not_called()

    def test_new_cluster_creates_theme_and_first_occurrence(self, mocker, historian_db):
        mocker.patch("app.embeddings.embed_batch", return_value=[[1.0, 0.0, 0.0]])
        state = {"clusters": [{"name": "Quiet luxury", "description": "understated wealth", "example_posts": ["a", "b"]}]}

        result = map_trend_history(state)

        history = result["clusters"][0]["history"]
        assert history["occurrence_count"] == 1
        assert history["recurrence_pattern"] == "unclear"

        session = historian_db()
        try:
            assert session.query(TrendTheme).count() == 1
            assert session.query(TrendOccurrence).count() == 1
        finally:
            session.close()

    def test_rerunning_same_day_with_matching_cluster_reuses_theme_without_duplicating(self, mocker, historian_db):
        mocker.patch("app.embeddings.embed_batch", return_value=[[1.0, 0.0, 0.0]])
        state_1 = {"clusters": [{"name": "Quiet luxury", "description": "understated wealth", "example_posts": []}]}
        map_trend_history(state_1)

        # Same-day rerun with a near-identical cluster (fresh LLM wording, same embedding)
        mocker.patch("app.embeddings.embed_batch", return_value=[[0.99, 0.01, 0.0]])
        state_2 = {"clusters": [{"name": "Quiet luxury aesthetic", "description": "understated wealth vibe", "example_posts": []}]}
        result = map_trend_history(state_2)

        session = historian_db()
        try:
            assert session.query(TrendTheme).count() == 1
            assert session.query(TrendOccurrence).count() == 1
        finally:
            session.close()
        assert result["clusters"][0]["history"]["occurrence_count"] == 1

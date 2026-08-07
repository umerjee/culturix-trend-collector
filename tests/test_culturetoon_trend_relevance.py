"""Tests for app/services/culturetoon_trend_relevance.py — semantic
relevance ranking of trend Personas/Clusters against a CultureToons
brand's own trend_interests. Mirrors this codebase's existing
fail-open-on-embedding-failure convention (culturetoon_memory.py)."""
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

from app.services.culturetoon_trend_relevance import (
    _cosine_similarity, get_interests_embedding, rank_by_relevance,
)


class _FakeBrand:
    def __init__(self, trend_interests, trend_interests_embedding=None):
        self.trend_interests = trend_interests
        self.trend_interests_embedding = trend_interests_embedding


class _FakeCandidate:
    def __init__(self, name, relevance_embedding=None):
        self.name = name
        self.relevance_embedding = relevance_embedding


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        assert _cosine_similarity([1, 0, 0], [1, 0, 0]) == 1.0

    def test_orthogonal_vectors_score_zero(self):
        assert _cosine_similarity([1, 0], [0, 1]) == 0.0

    def test_empty_or_mismatched_scores_zero(self):
        assert _cosine_similarity([], [1, 2]) == 0.0
        assert _cosine_similarity([1, 2], [1, 2, 3]) == 0.0

    def test_zero_vector_scores_zero_not_divide_by_zero(self):
        assert _cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0


class TestGetInterestsEmbedding:
    def test_computes_and_caches_when_missing(self, mocker):
        mock_embed = mocker.patch("app.embeddings.embed_text", return_value=[0.1, 0.2, 0.3])
        brand = _FakeBrand(trend_interests="family comedy")
        result = get_interests_embedding(brand)
        assert result == [0.1, 0.2, 0.3]
        assert brand.trend_interests_embedding == [0.1, 0.2, 0.3]
        mock_embed.assert_called_once_with("family comedy")

    def test_returns_cached_without_calling_embed_again(self, mocker):
        mock_embed = mocker.patch("app.embeddings.embed_text")
        brand = _FakeBrand(trend_interests="family comedy", trend_interests_embedding=[0.9, 0.9])
        result = get_interests_embedding(brand)
        assert result == [0.9, 0.9]
        mock_embed.assert_not_called()


class TestRankByRelevance:
    def test_ranks_descending_by_similarity(self, mocker):
        interests = [1.0, 0.0]
        close = _FakeCandidate("close", relevance_embedding=[1.0, 0.0])
        far = _FakeCandidate("far", relevance_embedding=[0.0, 1.0])
        session = mocker.Mock()

        ranked = rank_by_relevance(session, [far, close], lambda c: c.name, interests)
        assert [c.name for c in ranked] == ["close", "far"]

    def test_embeds_uncached_candidates_and_caches_result(self, mocker):
        mock_embed_batch = mocker.patch("app.embeddings.embed_batch", return_value=[[1.0, 0.0]])
        session = mocker.Mock()
        uncached = _FakeCandidate("uncached")
        ranked = rank_by_relevance(session, [uncached], lambda c: c.name, [1.0, 0.0])

        mock_embed_batch.assert_called_once_with(["uncached"])
        assert uncached.relevance_embedding == [1.0, 0.0]
        assert ranked == [uncached]
        session.flush.assert_called_once()

    def test_bounds_new_embeddings_per_request(self, mocker):
        # More than _MAX_NEW_EMBEDDINGS_PER_REQUEST (15) uncached candidates
        # in one call must only embed the first 15, not all of them —
        # Voyage's free tier is 3 req/min, this must stay bounded.
        mock_embed_batch = mocker.patch("app.embeddings.embed_batch", return_value=[[1.0]] * 15)
        session = mocker.Mock()
        candidates = [_FakeCandidate(f"c{i}") for i in range(20)]

        rank_by_relevance(session, candidates, lambda c: c.name, [1.0])

        embedded_count = sum(1 for c in candidates if c.relevance_embedding is not None)
        assert embedded_count == 15
        call_args = mock_embed_batch.call_args[0][0]
        assert len(call_args) == 15

    def test_embedding_failure_leaves_candidates_unscored_not_dropped(self, mocker):
        # Fail-open — same convention as culturetoon_memory.py's
        # retrieve_relevant_memories: an embedding outage must not make
        # candidates disappear from the picker, just leave them unranked.
        mocker.patch("app.embeddings.embed_batch", side_effect=RuntimeError("Voyage is down"))
        session = mocker.Mock()
        a = _FakeCandidate("a")
        b = _FakeCandidate("b", relevance_embedding=[1.0, 0.0])

        ranked = rank_by_relevance(session, [a, b], lambda c: c.name, [1.0, 0.0])

        assert set(c.name for c in ranked) == {"a", "b"}
        # b has a real embedding so it's scored/first; a (never embedded due
        # to the failure) is appended, unranked, not dropped.
        assert ranked[0].name == "b"
        assert ranked[-1].name == "a"

    def test_already_cached_candidates_are_not_re_embedded(self, mocker):
        mock_embed_batch = mocker.patch("app.embeddings.embed_batch")
        session = mocker.Mock()
        cached = _FakeCandidate("cached", relevance_embedding=[1.0, 0.0])

        rank_by_relevance(session, [cached], lambda c: c.name, [1.0, 0.0])

        mock_embed_batch.assert_not_called()

from app.pipeline.nodes.persona_mapper import (
    _cosine_similarity,
    _rank_clusters_by_relevance,
)


class TestCosineSimilarity:
    def test_identical_vectors_are_maximally_similar(self):
        assert _cosine_similarity([1, 2, 3], [1, 2, 3]) == 1.0

    def test_orthogonal_vectors_are_zero(self):
        assert _cosine_similarity([1, 0], [0, 1]) == 0.0

    def test_mismatched_or_empty_vectors_return_zero(self):
        assert _cosine_similarity([], [1, 2]) == 0.0
        assert _cosine_similarity([1, 2], [1, 2, 3]) == 0.0


class TestRankClustersByRelevance:
    def test_picks_the_most_similar_clusters_first(self, mocker):
        # Regression test for the actual bug report: a Beauty & Self-Care
        # profile's query vector should rank the beauty cluster above the
        # FIFA one, not just take whatever came first in the list.
        clusters = [
            {"name": "FIFA World Cup tournaments", "description": "..."},
            {"name": "Skincare routines going viral", "description": "..."},
        ]
        # FIFA cluster embedding is orthogonal to the query; beauty cluster
        # embedding points the same direction as the query.
        mocker.patch(
            "app.pipeline.nodes.persona_mapper._embed_clusters_as_documents",
            return_value=[[0.0, 1.0], [1.0, 0.0]],
        )
        query_vec = [1.0, 0.0]  # "beauty & self-care" query

        ranked = _rank_clusters_by_relevance(clusters, query_vec, top_n=2)

        assert ranked[0]["name"] == "Skincare routines going viral"
        assert ranked[1]["name"] == "FIFA World Cup tournaments"

    def test_respects_top_n(self, mocker):
        clusters = [{"name": f"cluster {i}", "description": ""} for i in range(5)]
        mocker.patch(
            "app.pipeline.nodes.persona_mapper._embed_clusters_as_documents",
            return_value=[[float(i), 0.0] for i in range(5)],
        )
        ranked = _rank_clusters_by_relevance(clusters, [1.0, 0.0], top_n=2)
        assert len(ranked) == 2

    def test_no_query_vec_falls_back_to_unranked_slice(self):
        clusters = [{"name": f"cluster {i}"} for i in range(10)]
        ranked = _rank_clusters_by_relevance(clusters, None, top_n=3)
        assert ranked == clusters[:3]

    def test_empty_clusters_returns_empty(self):
        assert _rank_clusters_by_relevance([], [1.0, 0.0]) == []

    def test_embedding_failure_falls_back_to_unranked_slice(self, mocker):
        clusters = [{"name": f"cluster {i}"} for i in range(10)]
        mocker.patch(
            "app.pipeline.nodes.persona_mapper._embed_clusters_as_documents",
            side_effect=RuntimeError("Voyage API down"),
        )
        ranked = _rank_clusters_by_relevance(clusters, [1.0, 0.0], top_n=3)
        assert ranked == clusters[:3]

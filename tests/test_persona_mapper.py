from app.pipeline.nodes.persona_mapper import (
    _cosine_similarity,
    _filter_by_region,
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


class TestFilterByRegion:
    def test_empty_target_regions_is_unrestricted(self):
        clusters = [{"name": "A", "regions": ["IN"]}, {"name": "B", "regions": ["US"]}]
        assert _filter_by_region(clusters, []) == clusters

    def test_global_in_target_regions_is_unrestricted(self):
        clusters = [{"name": "A", "regions": ["IN"]}, {"name": "B", "regions": ["US"]}]
        assert _filter_by_region(clusters, ["Global"]) == clusters

    def test_matching_region_is_kept(self):
        clusters = [{"name": "US cluster", "regions": ["US"]}]
        result = _filter_by_region(clusters, ["US"])
        assert result == clusters

    def test_regression_eu_profile_excludes_india_cluster(self):
        # The actual reported bug: target_regions=["EU"] getting an India-tagged
        # trend (an Indian movie, sourced from TikTok/YouTube's India charts).
        clusters = [
            {"name": "Indian movie trend", "regions": ["IN"]},
            {"name": "French fashion trend", "regions": ["FR"]},
        ]
        result = _filter_by_region(clusters, ["EU"])
        assert result == [{"name": "French fashion trend", "regions": ["FR"]}]

    def test_eu_covers_the_major_european_markets_not_just_fr_de(self):
        # "EU" used to only match FR/DE — too narrow for the "broad Europe"
        # sense it's meant to cover. GB is included deliberately (colloquial
        # Europe, not the strict political union — see persona_mapper.py's
        # comment on _REGION_LABEL_TO_CODES).
        for code in ("GB", "ES", "IT", "PT", "DE", "FR"):
            clusters = [{"name": f"{code} cluster", "regions": [code]}]
            assert _filter_by_region(clusters, ["EU"]) == clusters, f"{code} should match EU"

    def test_uk_label_maps_to_gb_collector_code(self):
        clusters = [{"name": "UK cluster", "regions": ["GB"]}]
        result = _filter_by_region(clusters, ["UK"])
        assert result == clusters

    def test_cluster_with_unknown_region_fails_open_and_is_kept(self):
        # No regions resolved (e.g. built entirely from Reddit/Bluesky signals) —
        # we have no basis to exclude it, unlike a cluster with a KNOWN
        # non-matching region.
        clusters = [{"name": "unknown region cluster", "regions": []}]
        result = _filter_by_region(clusters, ["EU"])
        assert result == clusters

    def test_unmapped_target_region_label_fails_open(self):
        clusters = [{"name": "A", "regions": ["IN"]}]
        result = _filter_by_region(clusters, ["SomeUnknownLabel"])
        assert result == clusters

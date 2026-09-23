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
        # Both point somewhat toward the query so both clear the relevance
        # floor, but skincare is a closer match (angle-of-45deg vs
        # orthogonal-ish) — isolates ranking order from floor filtering,
        # which test_relevance_floor_excludes_clearly_off_niche_clusters
        # below covers separately.
        mocker.patch(
            "app.pipeline.nodes.persona_mapper._embed_clusters_as_documents",
            return_value=[[0.3, 1.0], [1.0, 0.3]],
        )
        query_vec = [1.0, 0.0]  # "beauty & self-care" query

        ranked = _rank_clusters_by_relevance(clusters, query_vec, top_n=2)

        assert ranked[0]["name"] == "Skincare routines going viral"
        assert ranked[1]["name"] == "FIFA World Cup tournaments"

    def test_a_sustained_trend_outranks_an_equally_relevant_spike(self, mocker):
        # Phase 2 of the trend/cluster quality-scoring work: among similarly
        # on-niche clusters, a proven recurring interest should beat a one-off,
        # since content_strategist.py's clusters[:PROACTIVE_CLUSTER_COUNT] takes
        # this ranking's output directly — durability previously only reached
        # the prompt as descriptive text (_history_note), never selection.
        clusters = [
            {"name": "One-off event spike", "description": "...",
             "history": {"recurrence_pattern": "spike", "pattern_confidence": 0.9}},
            {"name": "Recurring weekly interest", "description": "...",
             "history": {"recurrence_pattern": "weekly", "pattern_confidence": 0.9}},
        ]
        # The spike cluster is given a very slightly HIGHER raw relevance than the
        # weekly one, so a relevance-only sort would rank it first — isolating the
        # durability blend as what actually flips the order.
        mocker.patch(
            "app.pipeline.nodes.persona_mapper._embed_clusters_as_documents",
            return_value=[[1.0, 0.0], [1.0, 0.02]],
        )
        query_vec = [1.0, 0.0]

        ranked = _rank_clusters_by_relevance(clusters, query_vec, top_n=2)

        assert ranked[0]["name"] == "Recurring weekly interest"

    def test_durability_cannot_override_a_clearly_stronger_relevance_match(self, mocker):
        # The blend must be a tie-breaker, not a replacement for relevance: a
        # barely-relevant sustained trend must not leapfrog a clearly more
        # relevant spike.
        clusters = [
            {"name": "Barely relevant but sustained", "description": "...",
             "history": {"recurrence_pattern": "weekly", "pattern_confidence": 0.9}},
            {"name": "Highly relevant spike", "description": "...",
             "history": {"recurrence_pattern": "spike", "pattern_confidence": 0.9}},
        ]
        mocker.patch(
            "app.pipeline.nodes.persona_mapper._embed_clusters_as_documents",
            return_value=[[0.2, 0.98], [1.0, 0.0]],
        )
        query_vec = [1.0, 0.0]

        ranked = _rank_clusters_by_relevance(clusters, query_vec, top_n=2)

        assert ranked[0]["name"] == "Highly relevant spike"

    def test_relevance_floor_excludes_clearly_off_niche_clusters(self, mocker):
        # Regression test for the second bug report: an Entertainment News
        # profile got GLP-1 drug side-effects content because ranking alone
        # (no floor) always padded out to top_n regardless of how weak the
        # actual match was.
        clusters = [
            {"name": "GLP-1 drug side effects Reddit analysis", "description": "..."},
            {"name": "Harry Styles 2027 Together Together Tour", "description": "..."},
        ]
        # GLP-1 embedding is orthogonal to the query (0.0 similarity, well
        # below _RELEVANCE_FLOOR); Harry Styles points the same direction.
        mocker.patch(
            "app.pipeline.nodes.persona_mapper._embed_clusters_as_documents",
            return_value=[[0.0, 1.0], [1.0, 0.0]],
        )
        query_vec = [1.0, 0.0]  # "Entertainment News" query

        ranked = _rank_clusters_by_relevance(clusters, query_vec, top_n=2)

        assert len(ranked) == 1
        assert ranked[0]["name"] == "Harry Styles 2027 Together Together Tour"

    def test_nothing_clears_the_floor_returns_single_best_not_empty(self, mocker):
        # A genuinely slow day for this niche shouldn't mean an empty digest
        # — the single best-available match beats padding with several
        # clearly-irrelevant ones, and beats returning nothing at all.
        clusters = [
            {"name": "GLP-1 drug side effects Reddit analysis", "description": "..."},
            {"name": "DR Congo Ebola Outbreak Deaths", "description": "..."},
        ]
        mocker.patch(
            "app.pipeline.nodes.persona_mapper._embed_clusters_as_documents",
            return_value=[[0.0, 1.0], [0.05, 1.0]],
        )
        query_vec = [1.0, 0.0]

        ranked = _rank_clusters_by_relevance(clusters, query_vec, top_n=2)

        assert len(ranked) == 1
        assert ranked[0]["name"] == "DR Congo Ebola Outbreak Deaths"  # the (barely) less-orthogonal one

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

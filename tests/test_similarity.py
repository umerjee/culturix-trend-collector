from app.pipeline.nodes._similarity import cosine_similarity, average_embedding, SIMILARITY_THRESHOLD
import app.pipeline.nodes.trend_historian as trend_historian
import app.pipeline.nodes.persona_tag_tracker as persona_tag_tracker


class TestCosineSimilarity:
    def test_identical_vectors_are_maximally_similar(self):
        assert cosine_similarity([1, 2, 3], [1, 2, 3]) == 1.0

    def test_orthogonal_vectors_are_zero(self):
        assert cosine_similarity([1, 0], [0, 1]) == 0.0

    def test_mismatched_or_empty_vectors_return_zero(self):
        assert cosine_similarity([], [1, 2]) == 0.0
        assert cosine_similarity([1, 2], [1, 2, 3]) == 0.0


class TestAverageEmbedding:
    def test_no_prior_centroid_returns_new_vector_unchanged(self):
        assert average_embedding([], [1, 2], 0) == [1, 2]

    def test_weighted_average_accounts_for_prior_occurrence_count(self):
        assert average_embedding([0, 0], [2, 2], 1) == [1.0, 1.0]


class TestSimilarityThreshold:
    def test_threshold_calibrated_below_real_measured_same_topic_pairs(self):
        # Regression guard for the 2026-07-23 recalibration (0.85 -> 0.75).
        # These are the actual voyage-3 cosine similarities measured between
        # real production TrendTheme pairs that are unambiguously the same
        # real-world trend, one day apart, reworded by a fresh LLM call —
        # see _similarity.py's module comment for the full write-up. Every
        # one of these fell BELOW the old 0.85 threshold, which is what
        # left /admin/trend-history stuck at "unclear" for 103/103 themes
        # despite 4 days of real operation. This test just asserts the
        # threshold stays low enough to catch them — if someone raises it
        # back toward 0.85 without re-measuring, this catches the regression.
        measured_same_topic_similarities = [0.844, 0.808, 0.798, 0.793, 0.769]
        for score in measured_same_topic_similarities:
            assert score >= SIMILARITY_THRESHOLD

    def test_both_consumers_import_the_shared_threshold_not_a_private_copy(self):
        assert trend_historian._SIMILARITY_THRESHOLD is SIMILARITY_THRESHOLD
        assert persona_tag_tracker._SIMILARITY_THRESHOLD is SIMILARITY_THRESHOLD

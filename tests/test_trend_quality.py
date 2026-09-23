from app.services import trend_quality as tq


class TestScoreGroupCorroboration:
    def test_single_platform_gets_no_corroboration_credit(self):
        result = tq.score_group(signal_count=5, platforms={"tiktok"}, title_keys={"a", "b", "c", "d", "e"})
        assert result.corroboration == 0.0

    def test_more_distinct_platforms_scores_higher_with_diminishing_returns(self):
        one = tq.score_group(signal_count=4, platforms={"tiktok"}, title_keys={"a", "b", "c", "d"})
        two = tq.score_group(signal_count=4, platforms={"tiktok", "youtube"}, title_keys={"a", "b", "c", "d"})
        four = tq.score_group(signal_count=4, platforms={"tiktok", "youtube", "reddit", "twitter"},
                              title_keys={"a", "b", "c", "d"})
        assert one.corroboration < two.corroboration < four.corroboration
        # 1->2 platforms should matter more than 3->4 (diminishing returns)
        three = tq.score_group(signal_count=4, platforms={"tiktok", "youtube", "reddit"},
                               title_keys={"a", "b", "c", "d"})
        assert (two.corroboration - one.corroboration) > (four.corroboration - three.corroboration)

    def test_no_platforms_is_zero_not_a_crash(self):
        result = tq.score_group(signal_count=0, platforms=set(), title_keys=set())
        assert result.corroboration == 0.0


class TestScoreGroupDiversity:
    def test_near_duplicate_spam_scores_low_diversity(self):
        # The exact motivating case: 163 near-identical TikTok captions, one platform.
        result = tq.score_group(signal_count=163, platforms={"tiktok"}, title_keys={"osmo action clip"})
        assert result.diversity < 0.05

    def test_all_unique_titles_scores_full_diversity(self):
        result = tq.score_group(signal_count=4, platforms={"tiktok"}, title_keys={"a", "b", "c", "d"})
        assert result.diversity == 1.0

    def test_a_spam_bucket_scores_lower_overall_than_a_real_curated_theme(self):
        # Regression-shaped: this is the exact ranking that was broken by a pure
        # signal_count sort (163-signal spam bucket outranking a real 4-signal theme).
        spam = tq.score_group(signal_count=163, platforms={"tiktok"}, title_keys={"osmo action clip"})
        real_theme = tq.score_group(signal_count=4, platforms={"google_trends", "tiktok"},
                                    title_keys={"nigerian newspapers", "security corps", "a", "b"},
                                    momentum="neutral")
        assert real_theme.score > spam.score


class TestScoreGroupPersistence:
    def test_up_momentum_scores_higher_than_neutral_which_scores_higher_than_down(self):
        up = tq.score_group(signal_count=4, platforms={"tiktok"}, title_keys={"a", "b", "c", "d"}, momentum="up")
        neutral = tq.score_group(signal_count=4, platforms={"tiktok"}, title_keys={"a", "b", "c", "d"}, momentum="neutral")
        down = tq.score_group(signal_count=4, platforms={"tiktok"}, title_keys={"a", "b", "c", "d"}, momentum="down")
        assert up.persistence > neutral.persistence > down.persistence

    def test_no_momentum_is_not_penalized_below_down(self):
        # Unknown (first sighting, or a raw source bucket with no Cluster at all)
        # must not score WORSE than a cluster known to be actively fading.
        unknown = tq.score_group(signal_count=4, platforms={"tiktok"}, title_keys={"a", "b", "c", "d"}, momentum=None)
        down = tq.score_group(signal_count=4, platforms={"tiktok"}, title_keys={"a", "b", "c", "d"}, momentum="down")
        assert unknown.persistence >= down.persistence


class TestScoreGroupSize:
    def test_size_factor_saturates_instead_of_scaling_linearly(self):
        small = tq.score_group(signal_count=5, platforms={"tiktok"}, title_keys=set(f"t{i}" for i in range(5)))
        huge = tq.score_group(signal_count=500, platforms={"tiktok"}, title_keys=set(f"t{i}" for i in range(500)))
        # Size grew 100x but the size_factor's contribution must not grow anywhere close to that.
        assert huge.size_factor < small.size_factor * 3

    def test_zero_signals_is_zero_not_a_crash(self):
        result = tq.score_group(signal_count=0, platforms=set(), title_keys=set())
        assert result.size_factor == 0.0
        assert result.score == 0.0


class TestComputeCohesion:
    def test_identical_vectors_are_maximally_cohesive(self):
        assert tq.compute_cohesion([[1.0, 0.0], [1.0, 0.0]]) == 1.0

    def test_orthogonal_vectors_are_zero_cohesion(self):
        assert tq.compute_cohesion([[1.0, 0.0], [0.0, 1.0]]) == 0.0

    def test_fewer_than_two_embeddings_is_none(self):
        assert tq.compute_cohesion([]) is None
        assert tq.compute_cohesion([[1.0, 0.0]]) is None


class TestScoreHistory:
    def test_weekly_pattern_with_high_confidence_scores_high(self):
        cluster = {"history": {"recurrence_pattern": "weekly", "pattern_confidence": 0.9}}
        assert tq.score_history(cluster) > 0.8

    def test_spike_pattern_scores_low_even_with_high_confidence(self):
        cluster = {"history": {"recurrence_pattern": "spike", "pattern_confidence": 0.9}}
        assert tq.score_history(cluster) < 0.2

    def test_low_confidence_dampens_the_pattern_score(self):
        confident = {"history": {"recurrence_pattern": "sustained", "pattern_confidence": 0.9}}
        unsure = {"history": {"recurrence_pattern": "sustained", "pattern_confidence": 0.5}}
        assert tq.score_history(confident) > tq.score_history(unsure)

    def test_falls_back_to_durability_when_no_history_pattern_yet(self):
        # A cluster's first day: trend_historian.py hasn't accumulated enough
        # occurrences for a pattern ('unclear' isn't a scored pattern), but
        # trend_validator.py's LLM-judged durability tag is already there.
        sustained = {"history": {"recurrence_pattern": "unclear", "pattern_confidence": 0.0}, "durability": "sustained"}
        spike = {"history": {"recurrence_pattern": "unclear", "pattern_confidence": 0.0}, "durability": "spike"}
        assert tq.score_history(sustained) == 1.0
        assert tq.score_history(spike) == 0.15

    def test_falls_back_to_durability_when_history_is_entirely_absent(self):
        sustained = {"durability": "sustained"}
        spike = {"durability": "spike"}
        neither = {}
        assert tq.score_history(sustained) == 1.0
        assert tq.score_history(spike) == 0.15
        assert tq.score_history(neither) == 0.0

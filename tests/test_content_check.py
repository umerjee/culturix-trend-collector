from datetime import datetime, timedelta

from app.pipeline.nodes.content_check import (
    _determine_status,
    _score_persona_fit,
    _score_trend_relevance,
    _score_platform_freshness,
)


class TestDetermineStatus:
    def test_high_score_is_live(self):
        assert _determine_status(100) == "live"
        assert _determine_status(80) == "live"

    def test_mid_score_is_aging(self):
        assert _determine_status(79) == "aging"
        assert _determine_status(50) == "aging"

    def test_low_score_is_stale(self):
        assert _determine_status(49) == "stale"
        assert _determine_status(0) == "stale"


class TestScorePersonaFit:
    def test_profile_unchanged_since_generation_scores_high(self):
        generated_at = datetime(2026, 1, 10)
        profile_updated_at = datetime(2026, 1, 1)  # updated before generation
        assert _score_persona_fit(generated_at, profile_updated_at) == 90

    def test_profile_changed_after_generation_scores_lower(self):
        generated_at = datetime(2026, 1, 1)
        profile_updated_at = datetime(2026, 1, 10)  # updated after generation
        assert _score_persona_fit(generated_at, profile_updated_at) == 60

    def test_missing_generated_at_defaults_to_good_fit(self):
        assert _score_persona_fit(None, datetime.utcnow()) == 90

    def test_missing_profile_updated_at_defaults_to_good_fit(self):
        assert _score_persona_fit(datetime.utcnow(), None) == 90


class TestScoreTrendRelevance:
    def test_no_trend_connection_returns_neutral_without_calling_llm(self, mocker):
        mock_llm = mocker.patch("app.pipeline.nodes.content_check._score_via_llm")
        idea = {"trend_connection": ""}
        assert _score_trend_relevance(idea, ["some recent post"]) == 50
        mock_llm.assert_not_called()

    def test_no_recent_texts_returns_neutral_without_calling_llm(self, mocker):
        mock_llm = mocker.patch("app.pipeline.nodes.content_check._score_via_llm")
        idea = {"trend_connection": "quiet luxury aesthetic"}
        assert _score_trend_relevance(idea, []) == 50
        mock_llm.assert_not_called()

    def test_delegates_to_llm_and_returns_its_score(self, mocker):
        mocker.patch(
            "app.pipeline.nodes.content_check._score_via_llm",
            return_value={"score": 87, "reason": "still trending"},
        )
        idea = {"trend_connection": "quiet luxury aesthetic"}
        assert _score_trend_relevance(idea, ["recent post"]) == 87

    def test_llm_response_missing_score_defaults_to_neutral(self, mocker):
        mocker.patch(
            "app.pipeline.nodes.content_check._score_via_llm",
            return_value={"reason": "malformed response"},
        )
        idea = {"trend_connection": "quiet luxury aesthetic"}
        assert _score_trend_relevance(idea, ["recent post"]) == 50


class TestScorePlatformFreshness:
    def test_no_hook_returns_neutral_without_calling_llm(self, mocker):
        mock_llm = mocker.patch("app.pipeline.nodes.content_check._score_via_llm")
        idea = {"hook": "", "platform": "TikTok"}
        assert _score_platform_freshness(idea, ["some recent post"]) == 50
        mock_llm.assert_not_called()

    def test_no_recent_texts_returns_neutral_without_calling_llm(self, mocker):
        mock_llm = mocker.patch("app.pipeline.nodes.content_check._score_via_llm")
        idea = {"hook": "POV you just found out...", "platform": "TikTok"}
        assert _score_platform_freshness(idea, []) == 50
        mock_llm.assert_not_called()

    def test_delegates_to_llm_and_returns_its_score(self, mocker):
        mocker.patch(
            "app.pipeline.nodes.content_check._score_via_llm",
            return_value={"score": 42, "reason": "oversaturated"},
        )
        idea = {"hook": "POV you just found out...", "platform": "TikTok"}
        assert _score_platform_freshness(idea, ["recent post"]) == 42

from unittest.mock import MagicMock

import pytest

from app.collectors.unesco import fetch_unesco_sites
from app.collectors.wikipedia_extracts import fetch_wikipedia_extract
from app.services import culturix_ingestion


class TestSourceCollectors:
    def test_wikipedia_extract_normalizes_article_shape(self, mocker):
        mocker.patch("httpx.get", return_value=MagicMock(
            is_success=True,
            json=lambda: {
                "title": "Strait of Hormuz",
                "extract": "A strategic waterway.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Strait_of_Hormuz"}},
                "coordinates": [{"lat": 26.5, "lon": 56.3}],
            },
        ))

        result = fetch_wikipedia_extract("Strait of Hormuz")

        assert result["title"] == "Strait of Hormuz"
        assert result["extract"] == "A strategic waterway."
        assert result["coordinates"] == {"lat": 26.5, "lon": 56.3}

    def test_wikipedia_returns_none_for_empty_extract(self, mocker):
        mocker.patch("httpx.get", return_value=MagicMock(is_success=True, json=lambda: {"extract": ""}))

        assert fetch_wikipedia_extract("Unknown") is None

    def test_unesco_maps_site_fields_and_region_filter(self, mocker):
        mock_get = mocker.patch("httpx.get", return_value=MagicMock(
            json=lambda: {"results": [{
                "id_no": 123,
                "name_en": "A Cultural Site",
                "short_description_en": "A real site.",
                "category": "Cultural",
                "iso_codes": ["IT"],
            }]},
        ))

        result = fetch_unesco_sites("it", limit=3)

        assert result[0]["id_no"] == 123
        assert result[0]["title"] == "A Cultural Site"
        assert result[0]["url"].endswith("/123")
        assert mock_get.call_args.kwargs["params"] == {
            "limit": 3,
            "where": 'iso_codes in ("IT")',
        }


class TestIngestionRules:
    def test_priority_score_uses_fixed_weighting(self):
        assert culturix_ingestion.compute_priority_score({
            "recency_score": 100,
            "popularity_score": 80,
            "cultural_weight": 60,
            "evergreen_value": 40,
        }) == 75

    def test_extract_items_discards_invalid_categories_and_caps_results(self, mocker):
        mocker.patch("app.services.culturix_ingestion._call_llm_json", return_value={"items": [
            {"title": "Keep", "summary": "Grounded.", "category": "history"},
            {"title": "Drop", "summary": "Unsupported.", "category": "fiction"},
            {"title": "Also keep", "summary": "Grounded.", "category": "culture"},
        ]})

        result = culturix_ingestion.extract_items("wikipedia", "IR", "source", max_items=1)

        assert result == [{"title": "Keep", "summary": "Grounded.", "category": "history"}]

    def test_score_and_challenge_clamps_scores_and_rejects_unknown_decision(self, mocker):
        mocker.patch("app.services.culturix_ingestion._call_llm_json", return_value={
            "recency_score": 120,
            "popularity_score": -4,
            "cultural_weight": 51.9,
            "evergreen_value": "bad",
            "challenge_notes": "Needs review.",
            "pipeline_decision": "maybe",
        })

        result = culturix_ingestion.score_and_challenge({
            "title": "A subject", "category": "history", "summary": "A summary",
        })

        assert result == {
            "recency_score": 100,
            "popularity_score": 0,
            "cultural_weight": 51,
            "evergreen_value": 50,
            "challenge_notes": "Needs review.",
            "pipeline_decision": "store_for_later",
        }

    def test_ingest_uses_source_and_title_for_stable_deduplication(self, mocker):
        mocker.patch("app.services.culturix_ingestion.extract_items", return_value=[{
            "title": "Site history", "summary": "Summary", "category": "history",
        }])
        mocker.patch("app.services.culturix_ingestion.score_and_challenge", return_value={
            "recency_score": 50, "popularity_score": 50,
            "cultural_weight": 50, "evergreen_value": 50,
            "challenge_notes": "Fine.", "pipeline_decision": "include",
        })
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None

        rows = culturix_ingestion.ingest("unesco", "IT", "raw", session, source_ref="123")

        assert len(rows) == 1
        assert rows[0].source_ref == "123:Site history"
        session.commit.assert_called_once()

    def test_score_failure_stores_for_later(self, mocker):
        mocker.patch(
            "app.services.culturix_ingestion._call_llm_json",
            side_effect=culturix_ingestion.IngestionError("API unavailable"),
        )

        result = culturix_ingestion.score_and_challenge({
            "title": "A subject", "category": "history", "summary": "A summary",
        })

        assert result["pipeline_decision"] == "store_for_later"
        assert result["recency_score"] == 50
        assert "API unavailable" in result["challenge_notes"]

class TestIngestionResilience:
    _ITEM = {"title": "Site history", "summary": "Summary", "category": "history"}

    def test_unscored_item_is_not_persisted(self, mocker):
        mocker.patch("app.services.culturix_ingestion.extract_items", return_value=[self._ITEM])
        mocker.patch("app.services.culturix_ingestion.score_and_challenge", return_value={
            "recency_score": 50, "popularity_score": 50, "cultural_weight": 50, "evergreen_value": 50,
            "challenge_notes": "Scoring failed: boom", "pipeline_decision": "store_for_later", "scoring_failed": True,
        })
        session = MagicMock()

        rows = culturix_ingestion.ingest("unesco", "IT", "raw", session, source_ref="123")

        assert rows == []
        session.add_all.assert_not_called()
        session.commit.assert_not_called()

    def test_scoring_failure_is_flagged(self, mocker):
        mocker.patch("app.services.culturix_ingestion._call_llm_json",
                     side_effect=culturix_ingestion.IngestionError("down"))
        assert culturix_ingestion.score_and_challenge(self._ITEM)["scoring_failed"] is True

    def test_read_transaction_is_closed_before_slow_scoring(self, mocker):
        order = []
        mocker.patch("app.services.culturix_ingestion.extract_items", return_value=[self._ITEM])
        mocker.patch("app.services.culturix_ingestion.score_and_challenge",
                     side_effect=lambda item: order.append("score") or {
                         "recency_score": 50, "popularity_score": 50, "cultural_weight": 50,
                         "evergreen_value": 50, "challenge_notes": "ok", "pipeline_decision": "include"})
        session = MagicMock()
        session.rollback.side_effect = lambda: order.append("rollback")

        culturix_ingestion.ingest("unesco", "IT", "raw", session, source_ref="123")

        assert order == ["rollback", "score"]

    def test_over_long_source_ref_is_truncated_to_the_column_width(self, mocker):
        mocker.patch("app.services.culturix_ingestion.extract_items",
                     return_value=[{**self._ITEM, "title": "T" * 400}])
        mocker.patch("app.services.culturix_ingestion.score_and_challenge", return_value={
            "recency_score": 50, "popularity_score": 50, "cultural_weight": 50, "evergreen_value": 50,
            "challenge_notes": "ok", "pipeline_decision": "include"})
        rows = culturix_ingestion.ingest("unesco", "IT", "raw", MagicMock(), source_ref="123")
        assert len(rows[0].source_ref) == 200

    def test_transient_llm_failure_is_retried_once(self, mocker):
        mocker.patch("app.services.culturix_ingestion.time.sleep")
        mocker.patch("os.getenv", return_value=None)
        claude = mocker.patch("app.services.culturix_ingestion._get_claude_client")
        good = MagicMock()
        good.content = [MagicMock(text='{"ok": true}')]
        claude.return_value.messages.create.side_effect = [ConnectionError("Connection error"), good]
        assert culturix_ingestion._call_llm_json("p") == {"ok": True}
        assert claude.return_value.messages.create.call_count == 2

    def test_invalid_json_is_not_retried(self, mocker):
        mocker.patch("os.getenv", return_value=None)
        claude = mocker.patch("app.services.culturix_ingestion._get_claude_client")
        bad = MagicMock()
        bad.content = [MagicMock(text="not json")]
        claude.return_value.messages.create.return_value = bad
        with pytest.raises(culturix_ingestion.IngestionError):
            culturix_ingestion._call_llm_json("p")
        assert claude.return_value.messages.create.call_count == 1


class TestSourceEnrichment:
    def test_article_search_accepts_a_title_sharing_a_significant_word(self, mocker):
        from app.collectors import wikipedia_extracts as w
        mocker.patch("httpx.get", return_value=MagicMock(is_success=True, json=lambda: ["q", ["Carcassonne"], [], []]))
        fetch = mocker.patch.object(w, "fetch_wikipedia_extract", return_value={"title": "Carcassonne", "extract": "Body"})
        assert w.find_wikipedia_article("Historic Fortified City of Carcassonne")["title"] == "Carcassonne"
        assert fetch.call_args.args == ("Carcassonne",) and fetch.call_args.kwargs["full_text"] is True

    def test_article_search_rejects_an_unrelated_hit(self, mocker):
        from app.collectors import wikipedia_extracts as w
        mocker.patch("httpx.get", return_value=MagicMock(is_success=True, json=lambda: ["q", ["Fortification"], [], []]))
        fetch = mocker.patch.object(w, "fetch_wikipedia_extract")
        assert w.find_wikipedia_article("Historic Fortified City of Carcassonne") is None
        fetch.assert_not_called()

    def test_article_search_never_raises(self, mocker):
        from app.collectors import wikipedia_extracts as w
        mocker.patch("httpx.get", side_effect=RuntimeError("network"))
        assert w.find_wikipedia_article("Anything") is None

    def test_unesco_source_text_appends_a_labeled_wikipedia_section(self, mocker):
        from app.collectors.unesco import unesco_source_text
        mocker.patch("app.collectors.wikipedia_extracts.find_wikipedia_article",
                     return_value={"title": "Carcassonne", "extract": "Deep detail.", "url": "https://en.wikipedia.org/wiki/Carcassonne"})
        text = unesco_source_text({"title": "Site", "description": "Short.", "category": "Cultural"})
        assert text.startswith("Site\nShort.\nCultural")
        assert 'Wikipedia article "Carcassonne" (https://en.wikipedia.org/wiki/Carcassonne):\nDeep detail.' in text

    def test_unesco_source_text_falls_back_to_unesco_only(self, mocker):
        from app.collectors.unesco import unesco_source_text
        mocker.patch("app.collectors.wikipedia_extracts.find_wikipedia_article", return_value=None)
        assert unesco_source_text({"title": "Site", "description": "Short."}) == "Site\nShort."

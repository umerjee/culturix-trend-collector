from unittest.mock import MagicMock

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
import json

from app.pipeline.nodes.trend_validator import validate_clusters, validate_ideas


def _mock_llm_json(mocker, target: str, payload: list):
    return mocker.patch(
        f"app.pipeline.nodes.trend_validator.{target}",
        return_value=json.dumps(payload),
    )


class TestValidateClusters:
    def test_legitimate_and_safe_cluster_is_kept_and_tagged(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"legitimate": True, "safe": True, "durability": "sustained", "reason": "ok"},
        ])
        state = {"clusters": [{"name": "Anime fandom", "description": "...", "example_posts": []}]}

        result = validate_clusters(state)

        assert len(result["clusters"]) == 1
        assert result["clusters"][0]["durability"] == "sustained"

    def test_illegitimate_cluster_is_hard_filtered_out(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"legitimate": False, "safe": True, "durability": "unclear", "reason": "hallucinated grouping"},
        ])
        state = {"clusters": [{"name": "Nonsense cluster", "description": "...", "example_posts": []}]}

        result = validate_clusters(state)

        assert result["clusters"] == []

    def test_unsafe_cluster_is_hard_filtered_out_even_if_legitimate(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"legitimate": True, "safe": False, "durability": "sustained", "reason": "hate speech"},
        ])
        state = {"clusters": [{"name": "Bad topic", "description": "...", "example_posts": []}]}

        result = validate_clusters(state)

        assert result["clusters"] == []

    def test_spike_durability_is_soft_tagged_not_filtered(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"legitimate": True, "safe": True, "durability": "spike", "reason": "tied to World Cup final"},
        ])
        state = {"clusters": [{"name": "World Cup final", "description": "...", "example_posts": []}]}

        result = validate_clusters(state)

        assert len(result["clusters"]) == 1
        assert result["clusters"][0]["durability"] == "spike"

    def test_mixed_batch_filters_only_illegitimate_or_unsafe(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"legitimate": True, "safe": True, "durability": "sustained", "reason": "ok"},
            {"legitimate": False, "safe": True, "durability": "unclear", "reason": "hallucinated"},
            {"legitimate": True, "safe": False, "durability": "sustained", "reason": "unsafe"},
            {"legitimate": True, "safe": True, "durability": "spike", "reason": "event-driven"},
        ])
        state = {"clusters": [
            {"name": "Keep A", "description": "...", "example_posts": []},
            {"name": "Drop B", "description": "...", "example_posts": []},
            {"name": "Drop C", "description": "...", "example_posts": []},
            {"name": "Keep D", "description": "...", "example_posts": []},
        ]}

        result = validate_clusters(state)

        kept_names = {c["name"] for c in result["clusters"]}
        assert kept_names == {"Keep A", "Keep D"}

    def test_empty_clusters_short_circuits_without_calling_llm(self, mocker):
        mock_llm = mocker.patch("app.pipeline.nodes.trend_validator._call_validation_llm")
        state = {"clusters": []}

        result = validate_clusters(state)

        assert result["clusters"] == []
        mock_llm.assert_not_called()

    def test_llm_failure_fails_open_and_keeps_all_clusters(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._call_validation_llm", side_effect=RuntimeError("API down"))
        clusters = [{"name": "A", "description": "...", "example_posts": []}]
        state = {"clusters": list(clusters), "errors": []}

        result = validate_clusters(state)

        assert result["clusters"] == clusters
        assert any("validate_clusters" in e for e in result["errors"])

    def test_result_count_mismatch_fails_open_and_keeps_all_clusters(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"legitimate": True, "safe": True, "durability": "sustained", "reason": "ok"},
        ])
        clusters = [
            {"name": "A", "description": "...", "example_posts": []},
            {"name": "B", "description": "...", "example_posts": []},
        ]
        state = {"clusters": list(clusters)}

        result = validate_clusters(state)

        assert result["clusters"] == clusters


class TestValidateIdeas:
    def test_safe_and_coherent_idea_is_kept(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"safe": True, "coherent": True, "reason": "fine"},
        ])
        state = {"generated_content": [
            {"user_id": "u1", "ideas": [{"hook": "POV you just found out", "caption": "...", "cta": "..."}]},
        ]}

        result = validate_ideas(state)

        assert len(result["generated_content"][0]["ideas"]) == 1

    def test_unsafe_idea_is_dropped(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"safe": False, "coherent": True, "reason": "harassment"},
        ])
        state = {"generated_content": [
            {"user_id": "u1", "ideas": [{"hook": "bad idea", "caption": "...", "cta": "..."}]},
        ]}

        result = validate_ideas(state)

        assert result["generated_content"][0]["ideas"] == []

    def test_incoherent_idea_is_dropped(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"safe": True, "coherent": False, "reason": "garbled"},
        ])
        state = {"generated_content": [
            {"user_id": "u1", "ideas": [{"hook": "asdkfj asdkfj", "caption": "...", "cta": "..."}]},
        ]}

        result = validate_ideas(state)

        assert result["generated_content"][0]["ideas"] == []

    def test_multiple_profiles_validated_independently(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        mock_llm = mocker.patch("app.pipeline.nodes.trend_validator._call_validation_llm")
        mock_llm.side_effect = [
            json.dumps([{"safe": True, "coherent": True, "reason": "ok"}]),
            json.dumps([{"safe": False, "coherent": True, "reason": "unsafe"}]),
        ]
        state = {"generated_content": [
            {"user_id": "u1", "ideas": [{"hook": "good", "caption": "...", "cta": "..."}]},
            {"user_id": "u2", "ideas": [{"hook": "bad", "caption": "...", "cta": "..."}]},
        ]}

        result = validate_ideas(state)

        assert len(result["generated_content"][0]["ideas"]) == 1
        assert result["generated_content"][1]["ideas"] == []

    def test_profile_with_no_ideas_is_skipped_without_calling_llm(self, mocker):
        mock_llm = mocker.patch("app.pipeline.nodes.trend_validator._call_validation_llm")
        state = {"generated_content": [{"user_id": "u1", "ideas": []}]}

        result = validate_ideas(state)

        assert result["generated_content"][0]["ideas"] == []
        mock_llm.assert_not_called()

    def test_llm_failure_fails_open_and_keeps_all_ideas_for_that_profile(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._call_validation_llm", side_effect=RuntimeError("API down"))
        ideas = [{"hook": "good", "caption": "...", "cta": "..."}]
        state = {"generated_content": [{"user_id": "u1", "ideas": list(ideas)}]}

        result = validate_ideas(state)

        assert result["generated_content"][0]["ideas"] == ideas

    def test_generic_idea_with_no_named_entity_is_dropped_even_if_safe_and_coherent(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"safe": True, "coherent": True, "specific": False, "reason": "never names who's actually feuding"},
        ])
        state = {"generated_content": [
            {"user_id": "u1", "ideas": [{
                "hook": "This celebrity feud just got MESSY",
                "caption": "The internet is DIVIDED...",
                "cta": "Drop your take",
                "trend_connection": "Celebrity drama trend",
            }]},
        ]}

        result = validate_ideas(state)

        assert result["generated_content"][0]["ideas"] == []

    def test_specific_idea_naming_a_real_entity_is_kept(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"safe": True, "coherent": True, "specific": True, "reason": "names the actual film and actors"},
        ])
        state = {"generated_content": [
            {"user_id": "u1", "ideas": [{
                "hook": "The Mummy reboot just cast Paul Mescal and fans are LOSING it",
                "caption": "...", "cta": "...", "trend_connection": "The Mummy (2027) casting news",
            }]},
        ]}

        result = validate_ideas(state)

        assert len(result["generated_content"][0]["ideas"]) == 1

    def test_result_count_mismatch_fails_open_and_keeps_all_ideas(self, mocker):
        mocker.patch("app.pipeline.nodes.trend_validator._log_validation")
        _mock_llm_json(mocker, "_call_validation_llm", [
            {"safe": True, "coherent": True, "reason": "ok"},
        ])
        ideas = [
            {"hook": "A", "caption": "...", "cta": "..."},
            {"hook": "B", "caption": "...", "cta": "..."},
        ]
        state = {"generated_content": [{"user_id": "u1", "ideas": list(ideas)}]}

        result = validate_ideas(state)

        assert result["generated_content"][0]["ideas"] == ideas

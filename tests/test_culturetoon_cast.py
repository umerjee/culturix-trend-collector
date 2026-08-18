"""Tests for app/services/culturetoon_cast.py — "Describe your show" bulk
cast generation, mirroring test_culturetoon_relationship.py/
test_culturetoon_personality.py's _mock_qwen_response mocking pattern for
the same Qwen-max/Haiku-fallback provider shape."""
import json
import os

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import pytest

from app.services.culturetoon_cast import (
    generate_cast_plan, CastGenerationError, MIN_CAST_SIZE, MAX_CAST_SIZE,
)


def _mock_qwen_response(mocker, payload: dict):
    os.environ["QWEN_API_KEY"] = "test-key"
    fake_message = mocker.Mock()
    fake_message.content = json.dumps(payload)
    fake_choice = mocker.Mock()
    fake_choice.message = fake_message
    fake_response = mocker.Mock()
    fake_response.choices = [fake_choice]

    fake_client = mocker.Mock()
    fake_client.chat.completions.create.return_value = fake_response
    mocker.patch("app.services.culturetoon_cast._get_qwen_client", return_value=fake_client)
    return fake_client


_TWO_CHARACTER_PAYLOAD = {
    "characters": [
        {
            "name": "Kumar", "description": "The strict dad.", "suggested_main": True,
            "personality": {
                "traits": {"confidence": 0.9, "humor": 0.6},
                "behavioral_rules": ["insists on doing things the right way"],
                "speech_rules": ["speaks formally"],
            },
        },
        {
            "name": "Priya", "description": "The easygoing mom.", "suggested_main": False,
            "personality": {
                "traits": {"warmth": 0.9},
                "behavioral_rules": ["smooths over conflicts"],
                "speech_rules": ["speaks warmly"],
            },
        },
    ],
    "relationships": [
        {
            "character_a_index": 0, "character_b_index": 1,
            "relationship_type": "husband_wife", "relationship_type_label": "Husband & Wife",
            "description": "Married, opposite temperaments.", "comedy_chemistry": 8,
            "a_to_b": {"affection_level": 8, "trust_level": 9, "conflict_level": 3, "behavior_rules": ["defers to her on social plans"]},
            "b_to_a": {"affection_level": 9, "trust_level": 8, "conflict_level": 2, "behavior_rules": ["teases his strictness"]},
        },
    ],
}


class TestGenerateCastPlan:
    def test_full_draft_shape(self, mocker):
        _mock_qwen_response(mocker, _TWO_CHARACTER_PAYLOAD)

        draft = generate_cast_plan("A sitcom about an Indian family running a shop.")

        assert len(draft["characters"]) == 2
        assert draft["characters"][0]["name"] == "Kumar"
        assert draft["characters"][0]["suggested_main"] is True
        assert draft["characters"][1]["suggested_main"] is False
        assert draft["characters"][0]["personality"]["traits"]["confidence"] == 0.9
        # Traits the model didn't return still default to 0.5, same
        # contract as generate_character_personality.
        assert draft["characters"][0]["personality"]["traits"]["patience"] == 0.5

        assert len(draft["relationships"]) == 1
        rel = draft["relationships"][0]
        assert rel["character_a_index"] == 0
        assert rel["character_b_index"] == 1
        assert rel["relationship_type"] == "husband_wife"
        assert rel["a_to_b"]["affection_level"] == 8
        assert rel["b_to_a"]["affection_level"] == 9

    def test_empty_plan_description_raises(self, mocker):
        with pytest.raises(CastGenerationError):
            generate_cast_plan("")

    def test_no_characters_returned_raises(self, mocker):
        _mock_qwen_response(mocker, {"characters": [], "relationships": []})
        with pytest.raises(CastGenerationError):
            generate_cast_plan("A show with nobody in it.")

    def test_cast_size_capped_at_max(self, mocker):
        characters = [
            {"name": f"Character {i}", "description": "x", "suggested_main": i == 0, "personality": {}}
            for i in range(10)
        ]
        _mock_qwen_response(mocker, {"characters": characters, "relationships": []})

        draft = generate_cast_plan("A huge ensemble show.")

        assert len(draft["characters"]) == MAX_CAST_SIZE

    def test_exactly_one_main_even_if_model_marks_none(self, mocker):
        characters = [
            {"name": "A", "description": "x", "suggested_main": False, "personality": {}},
            {"name": "B", "description": "y", "suggested_main": False, "personality": {}},
        ]
        _mock_qwen_response(mocker, {"characters": characters, "relationships": []})

        draft = generate_cast_plan("A show.")

        assert sum(1 for c in draft["characters"] if c["suggested_main"]) == 1

    def test_exactly_one_main_even_if_model_marks_several(self, mocker):
        characters = [
            {"name": "A", "description": "x", "suggested_main": True, "personality": {}},
            {"name": "B", "description": "y", "suggested_main": True, "personality": {}},
        ]
        _mock_qwen_response(mocker, {"characters": characters, "relationships": []})

        draft = generate_cast_plan("A show.")

        assert sum(1 for c in draft["characters"] if c["suggested_main"]) == 1
        assert draft["characters"][0]["suggested_main"] is True

    def test_relationship_with_out_of_range_index_is_dropped(self, mocker):
        payload = dict(_TWO_CHARACTER_PAYLOAD)
        payload["relationships"] = [
            {**_TWO_CHARACTER_PAYLOAD["relationships"][0], "character_b_index": 99},
        ]
        _mock_qwen_response(mocker, payload)

        draft = generate_cast_plan("A show.")

        assert draft["relationships"] == []

    def test_relationship_with_self_reference_is_dropped(self, mocker):
        payload = dict(_TWO_CHARACTER_PAYLOAD)
        payload["relationships"] = [
            {**_TWO_CHARACTER_PAYLOAD["relationships"][0], "character_b_index": 0},
        ]
        _mock_qwen_response(mocker, payload)

        draft = generate_cast_plan("A show.")

        assert draft["relationships"] == []

    def test_unknown_relationship_type_falls_back_to_custom(self, mocker):
        payload = dict(_TWO_CHARACTER_PAYLOAD)
        payload["relationships"] = [
            {**_TWO_CHARACTER_PAYLOAD["relationships"][0], "relationship_type": "sworn_nemeses", "relationship_type_label": "Sworn Nemeses"},
        ]
        _mock_qwen_response(mocker, payload)

        draft = generate_cast_plan("A show.")

        assert draft["relationships"][0]["relationship_type"] == "custom"
        assert draft["relationships"][0]["relationship_type_label"] == "Sworn Nemeses"

    def test_invalid_json_raises_cast_generation_error(self, mocker):
        os.environ["QWEN_API_KEY"] = "test-key"
        fake_message = mocker.Mock()
        fake_message.content = "not json"
        fake_choice = mocker.Mock()
        fake_choice.message = fake_message
        fake_response = mocker.Mock()
        fake_response.choices = [fake_choice]
        fake_client = mocker.Mock()
        fake_client.chat.completions.create.return_value = fake_response
        mocker.patch("app.services.culturetoon_cast._get_qwen_client", return_value=fake_client)

        with pytest.raises(CastGenerationError):
            generate_cast_plan("A show.")

    def test_existing_character_names_included_in_prompt(self, mocker):
        fake_client = _mock_qwen_response(mocker, _TWO_CHARACTER_PAYLOAD)

        generate_cast_plan("A show.", existing_character_names=["Ravi", "Meera"])

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Ravi" in sent_prompt
        assert "Meera" in sent_prompt

    def test_min_cast_size_constant_matches_docstring_range(self):
        assert MIN_CAST_SIZE == 2
        assert MAX_CAST_SIZE == 6

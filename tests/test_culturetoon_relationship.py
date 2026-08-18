"""Tests for app/services/culturetoon_relationship.py — the "Generate
relationship" LLM draft, mirroring test_culturetoon_script.py's own
_mock_qwen_response mocking pattern for the same Qwen-max/Haiku-fallback
provider shape."""
import json
import os

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import pytest

from app.services.culturetoon_relationship import (
    generate_relationship_dynamic, RelationshipGenerationError, RELATIONSHIP_TYPE_KEYS,
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
    mocker.patch("app.services.culturetoon_relationship._get_qwen_client", return_value=fake_client)
    return fake_client


def _character(mocker, name, traits=None, behavioral_rules=None, speech_rules=None, description=None):
    c = mocker.Mock()
    c.name = name
    c.description = description
    c.personality = {
        "traits": traits or {}, "behavioral_rules": behavioral_rules or [], "speech_rules": speech_rules or [],
    }
    return c


class TestGenerateRelationshipDynamic:
    def test_full_draft_shape(self, mocker):
        kumar = _character(mocker, "Kumar", traits={"impulsiveness": 0.8}, behavioral_rules=["improvises constantly"])
        hans = _character(mocker, "Hans", traits={"formality": 0.9}, behavioral_rules=["follows rules exactly"])
        _mock_qwen_response(mocker, {
            "relationship_type": "friendly_rivalry",
            "relationship_type_label": "Friendly Rivalry",
            "description": "Friendly rivalry based on Kumar's improvisation versus Hans's obsession with rules.",
            "comedy_chemistry": 8,
            "a_to_b": {
                "affection_level": 7, "trust_level": 8, "conflict_level": 6,
                "perspective_description": "Hans takes rules too seriously.",
                "behavior_rules": ["tries to persuade Hans to bend rules", "calls Hans \"brother\" when asking for something"],
            },
            "b_to_a": {
                "affection_level": 6, "trust_level": 5, "conflict_level": 9,
                "perspective_description": "Kumar creates unnecessary chaos.",
                "behavior_rules": ["responds literally", "refuses to bend rules"],
            },
        })

        draft = generate_relationship_dynamic(kumar, hans, culture_a="indian", culture_b="swiss")

        assert draft["relationship_type"] == "friendly_rivalry"
        assert draft["relationship_type_label"] == "Friendly Rivalry"
        assert "improvisation" in draft["description"]
        assert draft["comedy_chemistry"] == 8
        assert draft["a_to_b"]["affection_level"] == 7
        assert draft["a_to_b"]["trust_level"] == 8
        assert draft["a_to_b"]["conflict_level"] == 6
        assert draft["a_to_b"]["perspective_description"] == "Hans takes rules too seriously."
        assert draft["a_to_b"]["behavior_rules"] == ["tries to persuade Hans to bend rules", "calls Hans \"brother\" when asking for something"]
        assert draft["b_to_a"]["affection_level"] == 6
        assert draft["b_to_a"]["conflict_level"] == 9
        assert draft["b_to_a"]["perspective_description"] == "Kumar creates unnecessary chaos."

    def test_directions_are_not_forced_symmetrical(self, mocker):
        # The generator must not average or otherwise force a_to_b == b_to_a.
        kumar = _character(mocker, "Kumar")
        hans = _character(mocker, "Hans")
        _mock_qwen_response(mocker, {
            "relationship_type": "siblings",
            "a_to_b": {"affection_level": 9, "trust_level": 9, "conflict_level": 1, "behavior_rules": []},
            "b_to_a": {"affection_level": 3, "trust_level": 2, "conflict_level": 8, "behavior_rules": []},
        })
        draft = generate_relationship_dynamic(kumar, hans)
        assert draft["a_to_b"]["affection_level"] != draft["b_to_a"]["affection_level"]
        assert draft["a_to_b"]["conflict_level"] != draft["b_to_a"]["conflict_level"]

    def test_unknown_relationship_type_falls_back_to_custom(self, mocker):
        kumar = _character(mocker, "Kumar")
        hans = _character(mocker, "Hans")
        _mock_qwen_response(mocker, {
            "relationship_type": "sworn_nemeses",  # not in RELATIONSHIP_TYPE_KEYS
            "relationship_type_label": "Sworn Nemeses",
            "a_to_b": {}, "b_to_a": {},
        })
        draft = generate_relationship_dynamic(kumar, hans)
        assert draft["relationship_type"] == "custom"
        assert draft["relationship_type_label"] == "Sworn Nemeses"

    def test_levels_clamped_to_0_10(self, mocker):
        kumar = _character(mocker, "Kumar")
        hans = _character(mocker, "Hans")
        _mock_qwen_response(mocker, {
            "relationship_type": "rivals",
            "comedy_chemistry": 15,  # out of range
            "a_to_b": {"affection_level": -3, "trust_level": 20, "conflict_level": 5, "behavior_rules": []},
            "b_to_a": {},
        })
        draft = generate_relationship_dynamic(kumar, hans)
        assert draft["comedy_chemistry"] == 10
        assert draft["a_to_b"]["affection_level"] == 0
        assert draft["a_to_b"]["trust_level"] == 10

    def test_relationship_type_always_one_of_allowed(self, mocker):
        kumar = _character(mocker, "Kumar")
        hans = _character(mocker, "Hans")
        _mock_qwen_response(mocker, {"relationship_type": "coworkers", "a_to_b": {}, "b_to_a": {}})
        draft = generate_relationship_dynamic(kumar, hans)
        assert draft["relationship_type"] in RELATIONSHIP_TYPE_KEYS

    def test_invalid_json_raises_relationship_generation_error(self, mocker):
        os.environ["QWEN_API_KEY"] = "test-key"
        fake_message = mocker.Mock()
        fake_message.content = "not json at all"
        fake_choice = mocker.Mock()
        fake_choice.message = fake_message
        fake_response = mocker.Mock()
        fake_response.choices = [fake_choice]
        fake_client = mocker.Mock()
        fake_client.chat.completions.create.return_value = fake_response
        mocker.patch("app.services.culturetoon_relationship._get_qwen_client", return_value=fake_client)

        kumar = _character(mocker, "Kumar")
        hans = _character(mocker, "Hans")
        with pytest.raises(RelationshipGenerationError):
            generate_relationship_dynamic(kumar, hans)

    def test_prompt_includes_personality_and_culture(self, mocker):
        kumar = _character(mocker, "Kumar", traits={"impulsiveness": 0.9}, behavioral_rules=["never backs down"], speech_rules=["speaks fast"])
        hans = _character(mocker, "Hans", traits={"formality": 0.95})
        fake_client = _mock_qwen_response(mocker, {"relationship_type": "coworkers", "a_to_b": {}, "b_to_a": {}})

        generate_relationship_dynamic(kumar, hans, culture_a="indian", culture_b="swiss")

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "never backs down" in sent_prompt
        assert "speaks fast" in sent_prompt
        assert "indian" in sent_prompt
        assert "swiss" in sent_prompt

    def test_hint_is_included_in_prompt_when_provided(self, mocker):
        kumar = _character(mocker, "Kumar")
        hans = _character(mocker, "Hans")
        fake_client = _mock_qwen_response(mocker, {"relationship_type": "coworkers", "a_to_b": {}, "b_to_a": {}})

        generate_relationship_dynamic(kumar, hans, hint="they're rivals for the same promotion")

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "they're rivals for the same promotion" in sent_prompt

    def test_no_hint_omits_guidance_line(self, mocker):
        kumar = _character(mocker, "Kumar")
        hans = _character(mocker, "Hans")
        fake_client = _mock_qwen_response(mocker, {"relationship_type": "coworkers", "a_to_b": {}, "b_to_a": {}})

        generate_relationship_dynamic(kumar, hans)

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Additional guidance from the creator" not in sent_prompt
        assert "Kumar" in sent_prompt and "Hans" in sent_prompt

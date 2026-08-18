"""Tests for app/services/culturetoon_personality.py — the "Generate
personality" LLM draft, mirroring test_culturetoon_relationship.py's own
_mock_qwen_response mocking pattern for the same Qwen-max/Haiku-fallback
provider shape."""
import json
import os

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import pytest

from app.services.culturetoon_personality import (
    generate_character_personality, PersonalityGenerationError, PERSONALITY_TRAIT_KEYS,
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
    mocker.patch("app.services.culturetoon_personality._get_qwen_client", return_value=fake_client)
    return fake_client


def _character(mocker, name="Kumar", description="A cheerful uncle", art_style="cartoon_3d"):
    c = mocker.Mock()
    c.name = name
    c.description = description
    c.art_style = art_style
    return c


class TestGenerateCharacterPersonality:
    def test_full_draft_shape(self, mocker):
        character = _character(mocker)
        _mock_qwen_response(mocker, {
            "traits": {"confidence": 0.9, "humor": 0.8, "warmth": 0.7},
            "behavioral_rules": ["always one-ups other people's stories"],
            "speech_rules": ["peppers sentences with dad jokes"],
        })

        draft = generate_character_personality(character, hint="loud uncle who loves cricket")

        assert set(draft["traits"].keys()) == set(PERSONALITY_TRAIT_KEYS)
        assert draft["traits"]["confidence"] == 0.9
        assert draft["traits"]["humor"] == 0.8
        # Traits the model didn't return still show up, defaulted to 0.5,
        # so the frontend's sliders always have a value for every known key.
        assert draft["traits"]["patience"] == 0.5
        assert draft["behavioral_rules"] == ["always one-ups other people's stories"]
        assert draft["speech_rules"] == ["peppers sentences with dad jokes"]

    def test_traits_are_clamped_to_0_1(self, mocker):
        character = _character(mocker)
        _mock_qwen_response(mocker, {
            "traits": {"confidence": 1.7, "humor": -0.3},
            "behavioral_rules": [], "speech_rules": [],
        })

        draft = generate_character_personality(character)

        assert draft["traits"]["confidence"] == 1.0
        assert draft["traits"]["humor"] == 0.0

    def test_non_list_rules_are_coerced_to_a_list(self, mocker):
        character = _character(mocker)
        _mock_qwen_response(mocker, {
            "traits": {}, "behavioral_rules": "just one rule", "speech_rules": [],
        })

        draft = generate_character_personality(character)

        assert draft["behavioral_rules"] == ["just one rule"]

    def test_invalid_json_raises_personality_generation_error(self, mocker):
        os.environ["QWEN_API_KEY"] = "test-key"
        fake_message = mocker.Mock()
        fake_message.content = "not json"
        fake_choice = mocker.Mock()
        fake_choice.message = fake_message
        fake_response = mocker.Mock()
        fake_response.choices = [fake_choice]
        fake_client = mocker.Mock()
        fake_client.chat.completions.create.return_value = fake_response
        mocker.patch("app.services.culturetoon_personality._get_qwen_client", return_value=fake_client)

        with pytest.raises(PersonalityGenerationError):
            generate_character_personality(_character(mocker))

    def test_falls_back_to_claude_when_no_qwen_key(self, mocker):
        os.environ.pop("QWEN_API_KEY", None)
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        fake_text_block = mocker.Mock()
        fake_text_block.text = json.dumps({
            "traits": {"confidence": 0.6}, "behavioral_rules": [], "speech_rules": [],
        })
        fake_message = mocker.Mock()
        fake_message.content = [fake_text_block]
        fake_client = mocker.Mock()
        fake_client.messages.create.return_value = fake_message
        mocker.patch("app.services.culturetoon_personality._get_claude_client", return_value=fake_client)

        draft = generate_character_personality(_character(mocker))

        assert draft["traits"]["confidence"] == 0.6
        fake_client.messages.create.assert_called_once()

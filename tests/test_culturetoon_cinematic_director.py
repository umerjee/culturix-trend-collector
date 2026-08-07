"""Tests for app/services/culturetoon_cinematic_director.py — AI shot-list
planning for a ToonScene. Mirrors test_culturetoon_script.py's/
test_culturetoon_relationship.py's own _mock_qwen_response pattern for the
same Qwen-max/Haiku-fallback provider shape."""
import json
import os

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import pytest

from app.services.culturetoon_cinematic_director import (
    plan_shots, CinematicDirectorError,
)


def _mock_qwen_response(mocker, payload):
    os.environ["QWEN_API_KEY"] = "test-key"
    fake_message = mocker.Mock()
    fake_message.content = json.dumps(payload)
    fake_choice = mocker.Mock()
    fake_choice.message = fake_message
    fake_response = mocker.Mock()
    fake_response.choices = [fake_choice]

    fake_client = mocker.Mock()
    fake_client.chat.completions.create.return_value = fake_response
    mocker.patch("app.services.culturetoon_cinematic_director._get_qwen_client", return_value=fake_client)
    return fake_client


_CAST = [
    {"variant_id": "v-kumar", "name": "Kumar", "description": "Chaotic improviser"},
    {"variant_id": "v-hans", "name": "Hans", "description": "Rule-obsessed"},
]

_VARIED_SHOTS = [
    {"shot_number": 1, "shot_type": "establishing", "duration_seconds": 2, "character_names": [],
     "action": "Wide shot of a Swiss recycling station", "emotion": None, "dialogue": None,
     "comedic_beat": "setup", "camera_framing": "wide, centered", "camera_angle": "eye level",
     "camera_movement": "static", "lens": "24mm wide", "composition": "rule of thirds", "lighting": "overcast daylight"},
    {"shot_number": 2, "shot_type": "wide", "duration_seconds": 3, "character_names": ["Kumar"],
     "action": "Kumar walks in holding a single trash bag", "emotion": "Confused", "dialogue": None,
     "comedic_beat": "exposition", "camera_framing": "tracking Kumar", "camera_angle": "eye level",
     "camera_movement": "tracking", "lens": "35mm", "composition": "leading room", "lighting": "natural"},
    {"shot_number": 3, "shot_type": "closeup", "duration_seconds": 2, "character_names": ["Hans"],
     "action": "Hans's eye twitches", "emotion": "Annoyed", "dialogue": None,
     "comedic_beat": "reaction", "camera_framing": "tight on eyes", "camera_angle": "eye level",
     "camera_movement": "static", "lens": "85mm portrait", "composition": "extreme close", "lighting": "hard key"},
    {"shot_number": 4, "shot_type": "reaction", "duration_seconds": 2, "character_names": ["Kumar"],
     "action": "Kumar shrugs", "emotion": "Shocked", "dialogue": "What? It's just trash.",
     "comedic_beat": "punchline", "camera_framing": "medium", "camera_angle": "low angle",
     "camera_movement": "push_in", "lens": "35mm", "composition": "centered", "lighting": "natural"},
]


class TestPlanShots:
    def test_returns_normalized_shot_list(self, mocker):
        _mock_qwen_response(mocker, _VARIED_SHOTS)
        result = plan_shots("Kumar discovers Swiss recycling", _CAST, tone="funny", target_duration_seconds=15)

        assert len(result) == 4
        assert [s["shot_number"] for s in result] == [1, 2, 3, 4]
        assert result[0]["shot_type"] == "establishing"
        assert result[0]["character_variant_ids"] == []
        assert result[1]["character_variant_ids"] == ["v-kumar"]
        assert result[2]["character_variant_ids"] == ["v-hans"]

    def test_does_not_produce_only_talking_head_shots(self, mocker):
        # The whole point of this service — verify the shot_type sequence
        # actually varies rather than defaulting to medium/two_shot every time.
        _mock_qwen_response(mocker, _VARIED_SHOTS)
        result = plan_shots("Kumar discovers Swiss recycling", _CAST)
        shot_types = {s["shot_type"] for s in result}
        assert len(shot_types) > 1
        assert "establishing" in shot_types

    def test_character_names_resolved_to_variant_ids(self, mocker):
        _mock_qwen_response(mocker, _VARIED_SHOTS)
        result = plan_shots("Kumar discovers Swiss recycling", _CAST)
        # Case-insensitive match against the cast list's own names.
        assert result[1]["character_variant_ids"] == ["v-kumar"]

    def test_unrecognized_character_name_silently_dropped_not_invented(self, mocker):
        shots = [dict(_VARIED_SHOTS[1])]
        shots[0] = {**shots[0], "character_names": ["Kumar", "Someone Not In Cast"]}
        _mock_qwen_response(mocker, shots)
        result = plan_shots("scene", _CAST)
        assert result[0]["character_variant_ids"] == ["v-kumar"]

    def test_invalid_shot_type_falls_back_to_medium(self, mocker):
        shots = [{**_VARIED_SHOTS[0], "shot_type": "not_a_real_type"}]
        _mock_qwen_response(mocker, shots)
        result = plan_shots("scene", _CAST)
        assert result[0]["shot_type"] == "medium"

    def test_invalid_comedic_beat_and_camera_movement_become_null(self, mocker):
        shots = [{**_VARIED_SHOTS[0], "comedic_beat": "nonsense", "camera_movement": "nonsense"}]
        _mock_qwen_response(mocker, shots)
        result = plan_shots("scene", _CAST)
        assert result[0]["comedic_beat"] is None
        assert result[0]["camera_movement"] is None

    def test_duration_clamped_to_1_5_seconds(self, mocker):
        shots = [{**_VARIED_SHOTS[0], "duration_seconds": 30}]
        _mock_qwen_response(mocker, shots)
        result = plan_shots("scene", _CAST)
        assert result[0]["duration_seconds"] == 5

    def test_empty_cast_raises(self, mocker):
        with pytest.raises(CinematicDirectorError):
            plan_shots("scene", [])

    def test_no_shots_returned_raises(self, mocker):
        _mock_qwen_response(mocker, [])
        with pytest.raises(CinematicDirectorError):
            plan_shots("scene", _CAST)

    def test_invalid_json_raises_cinematic_director_error(self, mocker):
        os.environ["QWEN_API_KEY"] = "test-key"
        fake_message = mocker.Mock()
        fake_message.content = "not json"
        fake_choice = mocker.Mock()
        fake_choice.message = fake_message
        fake_response = mocker.Mock()
        fake_response.choices = [fake_choice]
        fake_client = mocker.Mock()
        fake_client.chat.completions.create.return_value = fake_response
        mocker.patch("app.services.culturetoon_cinematic_director._get_qwen_client", return_value=fake_client)

        with pytest.raises(CinematicDirectorError):
            plan_shots("scene", _CAST)

    def test_prompt_includes_cast_and_location(self, mocker):
        fake_client = _mock_qwen_response(mocker, _VARIED_SHOTS)
        plan_shots("Kumar discovers Swiss recycling", _CAST, location_description="a Swiss recycling station", tone="chaotic")

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Kumar" in sent_prompt and "Hans" in sent_prompt
        assert "Swiss recycling station" in sent_prompt
        assert "chaotic" in sent_prompt

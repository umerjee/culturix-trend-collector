"""Tests for app/services/culturetoon_script.py — shot-structured, tone-aware
script generation and the build_kling_prompt() DSL assembler.
"""
import json
import os
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import pytest

from app.services.culturetoon_script import (
    generate_toon_script,
    build_kling_prompt,
    ToonScriptGenerationError,
    _assign_speakers,
)


_VALID_SHOTS = [
    {"shot_number": 1, "duration_seconds": 4, "action": "storms into the kitchen",
     "expression": "Annoyed", "dialogue": "You didn't eat?!"},
    {"shot_number": 2, "duration_seconds": 4, "action": "already reaching for a pan",
     "expression": "Smiling", "dialogue": None},
]


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
    mocker.patch("app.services.culturetoon_script._get_qwen_client", return_value=fake_client)
    return fake_client


class TestGenerateToonScript:
    def test_well_formed_response_parses(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="Reality TV drama", summary="a big blowup")

        _mock_qwen_response(mocker, {
            "hook_line": "When mom finds out",
            "shots": _VALID_SHOTS,
        })

        result = generate_toon_script(cluster, tone="funny")
        assert result["hook_line"] == "When mom finds out"
        assert result["tone"] == "funny"
        assert result["shots"] == _VALID_SHOTS
        assert result["total_duration_seconds"] == 8

    def test_fenced_json_response_still_parses(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")

        payload = {"hook_line": "H", "shots": _VALID_SHOTS}
        fake_message = mocker.Mock()
        fake_message.content = f"```json\n{json.dumps(payload)}\n```"
        fake_choice = mocker.Mock()
        fake_choice.message = fake_message
        fake_response = mocker.Mock()
        fake_response.choices = [fake_choice]
        fake_client = mocker.Mock()
        fake_client.chat.completions.create.return_value = fake_response
        os.environ["QWEN_API_KEY"] = "test-key"
        mocker.patch("app.services.culturetoon_script._get_qwen_client", return_value=fake_client)

        result = generate_toon_script(cluster)
        assert result["shots"] == _VALID_SHOTS

    def test_falls_back_to_claude_when_no_qwen_key(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        os.environ["QWEN_API_KEY"] = ""

        payload = {"hook_line": "H", "shots": _VALID_SHOTS}
        fake_text_block = mocker.Mock()
        fake_text_block.text = json.dumps(payload)
        fake_message = mocker.Mock()
        fake_message.content = [fake_text_block]
        fake_client = mocker.Mock()
        fake_client.messages.create.return_value = fake_message
        mocker.patch("app.services.culturetoon_script._get_claude_client", return_value=fake_client)

        result = generate_toon_script(cluster)
        assert result["shots"] == _VALID_SHOTS
        fake_client.messages.create.assert_called_once()
        assert fake_client.messages.create.call_args.kwargs["max_tokens"] == 900

    def test_malformed_response_raises_generation_error(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")

        fake_message = mocker.Mock()
        fake_message.content = "not valid json at all"
        fake_choice = mocker.Mock()
        fake_choice.message = fake_message
        fake_response = mocker.Mock()
        fake_response.choices = [fake_choice]
        fake_client = mocker.Mock()
        fake_client.chat.completions.create.return_value = fake_response
        os.environ["QWEN_API_KEY"] = "test-key"
        mocker.patch("app.services.culturetoon_script._get_qwen_client", return_value=fake_client)

        with pytest.raises(ToonScriptGenerationError):
            generate_toon_script(cluster)

    def test_variant_grounds_the_prompt(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        variant = mocker.Mock(name="Indian Mom")
        variant.name = "Indian Mom"
        variant.description = "warm but exasperated"
        variant.culture_tag = "indian"

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(cluster, variants=[variant], tone="satiric")

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Indian Mom" in sent_prompt
        assert "satiric" in sent_prompt

    def test_multiple_variants_names_real_cast_and_forbids_inventing_others(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.name = "Kumar"; kumar.description = "middle class man"; kumar.culture_tag = None
        wife = mocker.Mock(); wife.name = "Wife"; wife.description = "elegant"; wife.culture_tag = None

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(cluster, variants=[kumar, wife], tone="funny")

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Kumar" in sent_prompt
        assert "Wife" in sent_prompt
        assert "do not invent any other" in sent_prompt.lower()
        assert "speaker_name" in sent_prompt

    def test_multiple_variants_maps_speaker_name_to_speaker_variant_id(self, mocker):
        from app.models.cluster import Cluster
        import uuid as _uuid
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.id = _uuid.uuid4(); kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = None
        wife = mocker.Mock(); wife.id = _uuid.uuid4(); wife.name = "Wife"; wife.description = None; wife.culture_tag = None

        shots_with_speakers = [
            {"shot_number": 1, "duration_seconds": 4, "action": "storms in", "expression": "Annoyed",
             "dialogue": "Where were you?!", "speaker_name": "Wife"},
            {"shot_number": 2, "duration_seconds": 4, "action": "shrugs", "expression": "Deadpan",
             "dialogue": "Traffic.", "speaker_name": "Kumar"},
        ]
        _mock_qwen_response(mocker, {"hook_line": "H", "shots": shots_with_speakers})
        result = generate_toon_script(cluster, variants=[kumar, wife], tone="funny")

        assert result["shots"][0]["speaker_variant_id"] == str(wife.id)
        assert result["shots"][1]["speaker_variant_id"] == str(kumar.id)
        assert "speaker_name" not in result["shots"][0]

    def test_single_variant_no_speaker_field_in_prompt(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = None

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(cluster, variants=[kumar], tone="funny")

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "speaker_name" not in sent_prompt


class TestAssignSpeakers:
    def test_no_variants_returns_shots_unchanged(self):
        shots = [{"shot_number": 1, "speaker_name": "Kumar"}]
        assert _assign_speakers(shots, []) == shots

    def test_unmatched_speaker_name_leaves_no_speaker_variant_id(self, mocker):
        v = mocker.Mock(); v.id = "abc"; v.name = "Kumar"
        shots = [{"shot_number": 1, "speaker_name": "Someone Else"}]
        result = _assign_speakers(shots, [v])
        assert "speaker_variant_id" not in result[0]
        assert "speaker_name" not in result[0]

    def test_matches_case_insensitively(self, mocker):
        v = mocker.Mock(); v.id = "abc"; v.name = "Kumar"
        shots = [{"shot_number": 1, "speaker_name": "kumar"}]
        result = _assign_speakers(shots, [v])
        assert result[0]["speaker_variant_id"] == "abc"


class TestBuildKlingPrompt:
    def test_builds_expected_dsl(self):
        prompt = build_kling_prompt(_VALID_SHOTS, "Mom")
        assert prompt.startswith('shot 1, 4, @Mom, storms into the kitchen, annoyed expression, saying "You didn\'t eat?!".')
        assert "shot 2, 4, @Mom, already reaching for a pan, smiling expression." in prompt
        assert prompt.endswith(";")

    def test_empty_shots_raises(self):
        with pytest.raises(ToonScriptGenerationError, match="empty"):
            build_kling_prompt([], "Mom")

    def test_too_many_shots_raises(self):
        shots = [
            {"shot_number": i, "duration_seconds": 1, "action": "x", "expression": None, "dialogue": None}
            for i in range(1, 8)
        ]
        with pytest.raises(ToonScriptGenerationError, match="at most 6"):
            build_kling_prompt(shots, "Mom")

    def test_non_contiguous_shot_numbers_raises(self):
        shots = [
            {"shot_number": 1, "duration_seconds": 4, "action": "x", "expression": None, "dialogue": None},
            {"shot_number": 3, "duration_seconds": 4, "action": "y", "expression": None, "dialogue": None},
        ]
        with pytest.raises(ToonScriptGenerationError, match="contiguous"):
            build_kling_prompt(shots, "Mom")

    def test_total_duration_out_of_bounds_raises(self):
        shots = [{"shot_number": 1, "duration_seconds": 20, "action": "x", "expression": None, "dialogue": None}]
        with pytest.raises(ToonScriptGenerationError, match="between 3 and 15"):
            build_kling_prompt(shots, "Mom")

    def test_dialogue_free_shot_omits_saying_clause(self):
        shots = [{"shot_number": 1, "duration_seconds": 5, "action": "waves", "expression": None, "dialogue": None}]
        prompt = build_kling_prompt(shots, "Mom")
        assert prompt == "shot 1, 5, @Mom, waves.;"

    def test_multi_character_dict_picks_element_per_shot_speaker(self):
        shots = [
            {"shot_number": 1, "duration_seconds": 4, "action": "storms in", "expression": "Annoyed",
             "dialogue": "Where were you?!", "speaker_variant_id": "wife-id"},
            {"shot_number": 2, "duration_seconds": 4, "action": "shrugs", "expression": "Deadpan",
             "dialogue": "Traffic.", "speaker_variant_id": "kumar-id"},
        ]
        prompt = build_kling_prompt(shots, {"kumar-id": "Kumar", "wife-id": "Wife"})
        assert "shot 1, 4, @Wife," in prompt
        assert "shot 2, 4, @Kumar," in prompt

    def test_multi_character_dict_shot_without_speaker_uses_first_as_default(self):
        shots = [{"shot_number": 1, "duration_seconds": 5, "action": "waves", "expression": None, "dialogue": None}]
        prompt = build_kling_prompt(shots, {"kumar-id": "Kumar", "wife-id": "Wife"})
        assert prompt == "shot 1, 5, @Kumar, waves.;"

    def test_empty_element_map_raises(self):
        with pytest.raises(ToonScriptGenerationError, match="at least one element name"):
            build_kling_prompt(_VALID_SHOTS, {})

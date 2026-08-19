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
    judge_script_comedy,
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

    def test_prompt_pushes_toward_specific_escalating_comedy(self, mocker):
        # Confirmed live: with no exaggeration/specificity direction, output
        # came back mild ("we just... sleep. A lot.") instead of committed,
        # escalating, hyper-specific comedy. These directives — and the new
        # visual/dialogue_delivery schema fields — are what fix that.
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        variant = mocker.Mock(); variant.name = "Kumar"; variant.description = "loud"; variant.culture_tag = None

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(cluster, variants=[variant], tone="funny")

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"].lower()
        assert "specificity" in sent_prompt
        assert "escalat" in sent_prompt
        assert "commit" in sent_prompt
        assert '"visual"' in sent_prompt
        assert '"dialogue_delivery"' in sent_prompt
        assert "visual (string), action (string)" in sent_prompt

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


class TestPersonalityAndRelationshipContext:
    def test_personality_injected_for_single_character(self, mocker):
        from app.models.cluster import Cluster
        import uuid as _uuid
        cluster = Cluster(label=1, theme="X", summary="Y")
        char_id = _uuid.uuid4()
        kumar = mocker.Mock()
        kumar.name = "Kumar"; kumar.description = "middle class man"; kumar.culture_tag = None
        kumar.character_id = char_id

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(
            cluster, variants=[kumar], tone="funny",
            character_personalities={
                str(char_id): {
                    "traits": {"confidence": 0.9, "humor": 0.8},
                    "behavioral_rules": ["tries to negotiate when prices seem high"],
                    "speech_rules": ["speaks confidently"],
                }
            },
        )

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "confidence (0.9)" in sent_prompt
        assert "tries to negotiate when prices seem high" in sent_prompt
        assert "speaks confidently" in sent_prompt

    def test_no_personality_no_extra_text(self, mocker):
        from app.models.cluster import Cluster
        import uuid as _uuid
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock()
        kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = None
        kumar.character_id = _uuid.uuid4()

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(cluster, variants=[kumar], tone="funny", character_personalities=None)

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "traits:" not in sent_prompt

    def test_relationship_injected_when_cast_includes_both_characters(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = None
        hans = mocker.Mock(); hans.name = "Hans"; hans.description = None; hans.culture_tag = None

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(
            cluster, variants=[kumar, hans], tone="funny",
            relationships=[{
                "relationship_type": "friendly_rivalry", "relationship_type_label": "Friendly Rivalry",
                "description": "Kumar finds Hans excessively rule-oriented.",
                "directions": [
                    {
                        "from_character_name": "Kumar", "to_character_name": "Hans",
                        "behavior_rules": ["Kumar attempts to persuade Hans."],
                    },
                ],
            }],
        )

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Friendly Rivalry" in sent_prompt
        assert "excessively rule-oriented" in sent_prompt
        assert "Kumar attempts to persuade Hans" in sent_prompt

    def test_directional_dynamics_are_not_symmetrical(self, mocker):
        # The whole point of the directional refinement — Kumar's dynamic
        # toward Hans can differ from Hans's dynamic toward Kumar, and both
        # must reach the prompt independently, not averaged/collapsed.
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = None
        hans = mocker.Mock(); hans.name = "Hans"; hans.description = None; hans.culture_tag = None

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(
            cluster, variants=[kumar, hans], tone="funny",
            relationships=[{
                "comedy_chemistry": 8,
                "directions": [
                    {
                        "from_character_name": "Kumar", "to_character_name": "Hans",
                        "affection_level": 7, "trust_level": 8, "conflict_level": 6,
                        "perspective_description": "Hans takes rules too seriously.",
                        "behavior_rules": ["tries to persuade Hans to bend rules"],
                    },
                    {
                        "from_character_name": "Hans", "to_character_name": "Kumar",
                        "affection_level": 6, "trust_level": 5, "conflict_level": 9,
                        "perspective_description": "Kumar creates unnecessary chaos.",
                        "behavior_rules": ["responds literally", "refuses to bend rules"],
                    },
                ],
            }],
        )

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "comedy chemistry 8/10" in sent_prompt
        assert "Kumar toward Hans" in sent_prompt and "affection 7/10" in sent_prompt
        assert "Hans toward Kumar" in sent_prompt and "affection 6/10" in sent_prompt
        assert "trust 8/10" in sent_prompt and "trust 5/10" in sent_prompt
        assert "conflict 6/10" in sent_prompt and "conflict 9/10" in sent_prompt
        assert "Hans takes rules too seriously." in sent_prompt
        assert "Kumar creates unnecessary chaos." in sent_prompt
        assert "tries to persuade Hans to bend rules" in sent_prompt
        assert "responds literally" in sent_prompt and "refuses to bend rules" in sent_prompt

    def test_relationship_recent_events_injected(self, mocker):
        # recent_events (see resolve_relationships_for_cast) is the
        # relationship's history log — it must reach the prompt so a
        # script can reflect the trajectory, not just the static snapshot.
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = None
        hans = mocker.Mock(); hans.name = "Hans"; hans.description = None; hans.culture_tag = None

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(
            cluster, variants=[kumar, hans], tone="funny",
            relationships=[{
                "relationship_type": "friendly_rivalry",
                "directions": [],
                "recent_events": [
                    {"description": "Made up over chai"},
                    {"description": "Argued over samosas"},
                ],
            }],
        )

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Argued over samosas" in sent_prompt
        assert "Made up over chai" in sent_prompt
        # Rendered oldest-of-the-batch first, so it reads as a timeline —
        # the resolver hands events newest-first, so this must be reversed.
        assert sent_prompt.index("Argued over samosas") < sent_prompt.index("Made up over chai")

    def test_no_relationships_no_extra_section(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = None

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(cluster, variants=[kumar], tone="funny", relationships=None)

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Established relationship" not in sent_prompt

    def test_culture_context_injected_with_avoid_guidance(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = "indian"

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(
            cluster, variants=[kumar], tone="funny",
            cultures=[{
                "name": "Indian",
                "humor_sensitivity": "food and family jokes land well",
                "common_misunderstandings": ["assuming every guest must be fed"],
                "positive_traits": ["hospitable"],
                "stereotypes_to_avoid": ["accent mockery"],
            }],
        )

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "food and family jokes land well" in sent_prompt
        assert "assuming every guest must be fed" in sent_prompt
        assert "AVOID: accent mockery" in sent_prompt

    def test_no_cultures_no_extra_section(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = None

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(cluster, variants=[kumar], tone="funny", cultures=None)

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Cultural context" not in sent_prompt

    def test_performance_context_injected_verbatim(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = None

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(
            cluster, variants=[kumar], tone="funny",
            performance_context="\nPast performance for this cast: 3 posts, avg 1500 views, 12.0% engagement\n",
        )

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "avg 1500 views, 12.0% engagement" in sent_prompt

    def test_no_performance_context_no_extra_text(self, mocker):
        from app.models.cluster import Cluster
        cluster = Cluster(label=1, theme="X", summary="Y")
        kumar = mocker.Mock(); kumar.name = "Kumar"; kumar.description = None; kumar.culture_tag = None

        fake_client = _mock_qwen_response(mocker, {"hook_line": "H", "shots": _VALID_SHOTS})
        generate_toon_script(cluster, variants=[kumar], tone="funny", performance_context=None)

        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Past performance" not in sent_prompt


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

    def test_visual_and_dialogue_delivery_included_when_present(self):
        shots = [{
            "shot_number": 1, "duration_seconds": 4,
            "visual": "holding a massive drum, confetti mid-air",
            "action": "dancing manically", "expression": "Happy",
            "dialogue": "500-person feast!", "dialogue_delivery": "Loud & Hyped",
        }]
        prompt = build_kling_prompt(shots, "Kumar")
        assert "holding a massive drum, confetti mid-air" in prompt
        assert "dancing manically" in prompt
        assert 'saying "500-person feast!" (Loud & Hyped delivery)' in prompt

    def test_visual_and_dialogue_delivery_optional(self):
        # Scripts generated before these fields existed shouldn't break.
        prompt = build_kling_prompt(_VALID_SHOTS, "Mom")
        assert "delivery)" not in prompt

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


class TestJudgeScriptComedy:
    def test_scores_and_returns_feedback(self, mocker):
        fake_client = _mock_qwen_response(mocker, {
            "comedy_score": 35, "passes_bar": False,
            "feedback": "Hans's line is too mild — push the bureaucratic angle further.",
        })
        result = judge_script_comedy({"hook_line": "H", "shots": _VALID_SHOTS})

        assert result == {
            "comedy_score": 35, "passes_bar": False,
            "feedback": "Hans's line is too mild — push the bureaucratic angle further.",
            "judge_failed": False,
        }
        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "storms into the kitchen" in sent_prompt
        assert "You didn't eat?!" in sent_prompt
        assert "SPECIFICITY" in sent_prompt

    def test_includes_visual_and_dialogue_delivery_in_the_prompt(self, mocker):
        fake_client = _mock_qwen_response(mocker, {"comedy_score": 80, "passes_bar": True, "feedback": "Good."})
        judge_script_comedy({
            "hook_line": "H",
            "shots": [{
                "shot_number": 1, "duration_seconds": 4,
                "visual": "holding a massive drum, confetti mid-air", "action": "dancing manically",
                "expression": "Happy", "dialogue": "500-person feast!", "dialogue_delivery": "Loud & Hyped",
            }],
        })
        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "holding a massive drum, confetti mid-air" in sent_prompt
        assert "(Loud & Hyped)" in sent_prompt

    def test_fails_open_on_llm_error(self, mocker):
        # judge_script_comedy is advisory-only, called right after a real
        # script generation succeeded — a broken judge shouldn't take the
        # whole suggest/regenerate response down with it.
        mocker.patch("app.services.culturetoon_script._get_qwen_client", side_effect=RuntimeError("down"))
        os.environ["QWEN_API_KEY"] = "test-key"
        result = judge_script_comedy({"hook_line": "H", "shots": _VALID_SHOTS})
        assert result == {"comedy_score": None, "passes_bar": None, "feedback": None, "judge_failed": True}

    def test_fails_open_on_malformed_json(self, mocker):
        os.environ["QWEN_API_KEY"] = "test-key"
        fake_message = mocker.Mock()
        fake_message.content = "not json"
        fake_choice = mocker.Mock()
        fake_choice.message = fake_message
        fake_response = mocker.Mock()
        fake_response.choices = [fake_choice]
        fake_client = mocker.Mock()
        fake_client.chat.completions.create.return_value = fake_response
        mocker.patch("app.services.culturetoon_script._get_qwen_client", return_value=fake_client)

        result = judge_script_comedy({"hook_line": "H", "shots": _VALID_SHOTS})
        assert result["judge_failed"] is True

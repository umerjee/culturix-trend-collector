"""Tests for app/services/culturetoon_selfhosted_video.py — prompt building
from a ToonScript's shots, the cast LoRA-readiness gate, and (TestGenerate
VideoForToonSelfhosted below) the interactive-button orchestrator against
an existing Toon, mirroring tests/test_culturetoon_video.py's in-memory
SQLite/mocked-provider shape for the Kling counterpart."""
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.character_brand import CharacterBrand
from app.models.character import Character
from app.models.character_variant import CharacterVariant
from app.models.toon_script import ToonScript
from app.models.toon import Toon
from app.models.toon_background import ToonBackground
from app.models.generation_usage import GenerationUsage
from app.services.culturetoon_selfhosted_video import (
    build_prompt_from_script, resolve_ready_lora, generate_toon_video_selfhosted,
    generate_video_for_toon_selfhosted, SelfHostedVideoGenerationError,
    _resilient_commit, _gather_dialogue, _resolve_narration,
    _build_shot_prompt, _resolve_shot_variant,
)


@pytest.fixture(autouse=True)
def _no_real_sleep(mocker):
    mocker.patch("app.services.culturetoon_selfhosted_video._COMMIT_RETRY_BACKOFF_SECONDS", 0)


def _script(mocker, hook_line=None, shots=None, total_duration_seconds=None):
    s = mocker.Mock()
    s.hook_line = hook_line
    s.shots = shots or []
    s.total_duration_seconds = total_duration_seconds
    return s


def _variant(mocker, name="Kumar", lora_status="ready", lora_path="loras/kumar.safetensors",
             image_url="https://example.com/kumar.png", voice_provider="kling", elevenlabs_voice_id=None,
             id=None):
    v = mocker.Mock()
    v.id = id or name
    v.name = name
    v.lora_status = lora_status
    v.lora_path = lora_path
    v.image_url = image_url
    v.voice_provider = voice_provider
    v.elevenlabs_voice_id = elevenlabs_voice_id
    return v


class TestBuildPromptFromScript:
    def test_combines_hook_action_and_dialogue(self, mocker):
        script = _script(
            mocker, hook_line="When mom finds out",
            shots=[
                {"action": "storms into the kitchen", "dialogue": "You didn't eat?!"},
                {"action": "already reaching for a pan", "dialogue": None},
            ],
        )
        prompt = build_prompt_from_script(script)
        assert "When mom finds out" in prompt
        assert "storms into the kitchen" in prompt
        assert 'saying "You didn\'t eat?!"' in prompt
        assert "already reaching for a pan" in prompt

    def test_includes_visual_and_dialogue_delivery_when_present(self, mocker):
        script = _script(
            mocker, hook_line="H",
            shots=[{
                "visual": "holding a massive drum, confetti mid-air",
                "action": "dancing manically", "dialogue": "500-person feast!",
                "dialogue_delivery": "Loud & Hyped",
            }],
        )
        prompt = build_prompt_from_script(script)
        assert "holding a massive drum, confetti mid-air" in prompt
        assert 'saying "500-person feast!" (Loud & Hyped delivery)' in prompt

    def test_includes_camera_direction_when_present(self, mocker):
        script = _script(
            mocker, hook_line="H",
            shots=[{"action": "waves", "dialogue": None, "shot_type": "closeup", "camera_movement": "push_in"}],
        )
        prompt = build_prompt_from_script(script)
        assert "closeup shot" in prompt
        assert "push in camera movement" in prompt

    def test_no_content_falls_back_to_generic_prompt(self, mocker):
        script = _script(mocker, hook_line=None, shots=[])
        assert build_prompt_from_script(script) == "A character reacts to their day."

    def test_includes_expression_when_present(self, mocker):
        # Confirmed live 2026-08-30 on a real script: every shot carries an
        # expression field, but it was being silently dropped.
        script = _script(mocker, hook_line="H", shots=[
            {"action": "waves", "dialogue": None, "expression": "Confused"},
        ])
        prompt = build_prompt_from_script(script)
        assert "with a confused expression" in prompt

    def test_background_with_name_and_description_is_prepended(self, mocker):
        # Mock(name=...) is reserved by unittest.mock for the mock's own
        # repr name, not a settable `.name` attribute — must assign it
        # after construction instead.
        background = mocker.Mock(description="A cramped city apartment kitchen")
        background.name = "Kitchen"
        script = _script(mocker, hook_line="H", shots=[])
        prompt = build_prompt_from_script(script, background=background)
        assert prompt.startswith("Set in Kitchen: A cramped city apartment kitchen")

    def test_background_with_name_only(self, mocker):
        background = mocker.Mock(description=None)
        background.name = "Kitchen"
        script = _script(mocker, hook_line="H", shots=[])
        prompt = build_prompt_from_script(script, background=background)
        assert prompt.startswith("Set in Kitchen")

    def test_background_with_description_only(self, mocker):
        background = mocker.Mock(description="A cramped city apartment kitchen")
        background.name = None
        script = _script(mocker, hook_line="H", shots=[])
        prompt = build_prompt_from_script(script, background=background)
        assert prompt.startswith("A cramped city apartment kitchen")

    def test_no_background_omits_set_in_prefix(self, mocker):
        script = _script(mocker, hook_line="H", shots=[])
        prompt = build_prompt_from_script(script, background=None)
        assert "Set in" not in prompt


class TestGatherDialogue:
    def test_joins_dialogue_lines_in_order(self, mocker):
        script = _script(mocker, shots=[
            {"action": "waves", "dialogue": "Hello there"},
            {"action": "frowns", "dialogue": None},
            {"action": "points", "dialogue": "Rule 1: be on time"},
        ])
        assert _gather_dialogue(script) == "Hello there ... Rule 1: be on time"

    def test_no_dialogue_at_all_returns_empty_string(self, mocker):
        script = _script(mocker, shots=[{"action": "waves", "dialogue": None}])
        assert _gather_dialogue(script) == ""


class TestBuildShotPrompt:
    def test_combines_all_fields_for_one_shot(self, mocker):
        shot = {
            "shot_type": "closeup", "camera_movement": "push_in",
            "visual": "holding a drum", "action": "dancing", "expression": "Happy",
            "dialogue": "Let's go!", "dialogue_delivery": "Loud",
        }
        prompt = _build_shot_prompt(shot)
        assert "closeup shot" in prompt
        assert "push in camera movement" in prompt
        assert "holding a drum" in prompt
        assert "dancing" in prompt
        assert "with a happy expression" in prompt
        assert 'saying "Let\'s go!" (Loud delivery)' in prompt

    def test_empty_shot_returns_empty_string_not_a_fallback_phrase(self, mocker):
        assert _build_shot_prompt({}) == ""

    def test_background_prepended_when_given(self, mocker):
        # country/visual_style set explicitly to None: a bare mocker.Mock()
        # auto-creates them as Mock objects, which are truthy and would be
        # appended to the prompt as non-strings.
        background = mocker.Mock(description="A cramped kitchen", country=None, visual_style=None)
        background.name = "Kitchen"
        prompt = _build_shot_prompt({"action": "waves"}, background=background)
        assert prompt.startswith("Set in Kitchen: A cramped kitchen")

    def test_background_country_and_visual_style_reach_the_prompt(self, mocker):
        """Both are real ToonBackground columns that _build_shot_prompt
        previously ignored entirely — only name/description were read, so a
        Location's own art direction never influenced generation at all."""
        background = mocker.Mock(
            description="A cramped kitchen",
            country="Norway",
            visual_style="warm muted palette, overcast light",
        )
        background.name = "Kitchen"
        prompt = _build_shot_prompt({"action": "waves"}, background=background)
        assert "Located in Norway" in prompt
        assert "warm muted palette, overcast light" in prompt


class TestResolveShotVariant:
    def test_matches_speaker_variant_id(self, mocker):
        hans = _variant(mocker, name="Hans", id="hans-id")
        wen = _variant(mocker, name="Wen", id="wen-id")
        shot = {"speaker_variant_id": "wen-id"}
        assert _resolve_shot_variant(shot, [hans, wen]) is wen

    def test_falls_back_to_primary_when_no_speaker_id(self, mocker):
        hans = _variant(mocker, name="Hans", id="hans-id")
        wen = _variant(mocker, name="Wen", id="wen-id")
        shot = {"speaker_variant_id": None}
        assert _resolve_shot_variant(shot, [hans, wen]) is hans

    def test_falls_back_to_primary_when_speaker_id_not_in_cast(self, mocker):
        hans = _variant(mocker, name="Hans", id="hans-id")
        shot = {"speaker_variant_id": "someone-else-id"}
        assert _resolve_shot_variant(shot, [hans]) is hans


class TestResolveReadyLora:
    def test_returns_primary_variant_lora_path_when_all_ready(self, mocker):
        variants = [_variant(mocker, name="A"), _variant(mocker, name="B")]
        assert resolve_ready_lora(variants) == variants[0].lora_path

    def test_raises_when_any_variant_not_ready(self, mocker):
        variants = [_variant(mocker, name="A"), _variant(mocker, name="B", lora_status="training")]
        with pytest.raises(SelfHostedVideoGenerationError, match="B"):
            resolve_ready_lora(variants)

    def test_raises_when_lora_status_failed(self, mocker):
        variants = [_variant(mocker, lora_status="failed")]
        with pytest.raises(SelfHostedVideoGenerationError):
            resolve_ready_lora(variants)


class TestResolveNarration:
    def test_no_dialogue_returns_none_none(self, mocker):
        script = _script(mocker, shots=[{"action": "waves", "dialogue": None}])
        assert _resolve_narration(script, [_variant(mocker)]) == (None, None)

    def test_defaults_to_narration_text_when_voice_provider_is_kling(self, mocker):
        script = _script(mocker, shots=[{"action": "waves", "dialogue": "Hi"}])
        variants = [_variant(mocker, voice_provider="kling")]
        audio_bytes, text = _resolve_narration(script, variants, elevenlabs_api_key="a-real-key")
        assert audio_bytes is None
        assert text == "Hi"

    def test_defaults_to_narration_text_when_no_api_key_supplied(self, mocker):
        # voice_provider="elevenlabs" but no key was resolved (e.g. brand
        # never configured one) — must fail open to on-worker Chatterbox
        # synthesis (narration_text), not error.
        script = _script(mocker, shots=[{"action": "waves", "dialogue": "Hi"}])
        variants = [_variant(mocker, voice_provider="elevenlabs", elevenlabs_voice_id="voice-123")]
        audio_bytes, text = _resolve_narration(script, variants, elevenlabs_api_key=None)
        assert audio_bytes is None
        assert text == "Hi"

    def test_uses_elevenlabs_per_shot_synthesis_when_fully_configured(self, mocker):
        mock_synth = mocker.patch(
            "app.services.culturetoon_selfhosted_video._synthesize_narration_elevenlabs",
            return_value=b"elevenlabs-bytes",
        )
        script = _script(mocker, shots=[{"action": "waves", "dialogue": "Hi"}])
        variants = [_variant(mocker, voice_provider="elevenlabs", elevenlabs_voice_id="voice-123")]
        audio_bytes, text = _resolve_narration(script, variants, elevenlabs_api_key="a-real-key")
        assert audio_bytes == b"elevenlabs-bytes"
        assert text is None
        mock_synth.assert_called_once_with(script, "a-real-key", "voice-123")

    def test_elevenlabs_failure_falls_back_to_narration_text(self, mocker):
        mocker.patch(
            "app.services.culturetoon_selfhosted_video._synthesize_narration_elevenlabs",
            side_effect=RuntimeError("ElevenLabs API error"),
        )
        script = _script(mocker, shots=[{"action": "waves", "dialogue": "Hi"}])
        variants = [_variant(mocker, voice_provider="elevenlabs", elevenlabs_voice_id="voice-123")]
        audio_bytes, text = _resolve_narration(script, variants, elevenlabs_api_key="a-real-key")
        assert audio_bytes is None
        assert text == "Hi"


class TestGenerateToonVideoSelfhosted:
    def test_raises_before_calling_runpod_when_cast_not_ready(self, mocker):
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job")
        script = _script(mocker, hook_line="hi", shots=[{"action": "waves"}])
        variants = [_variant(mocker, lora_status="none")]
        with pytest.raises(SelfHostedVideoGenerationError):
            generate_toon_video_selfhosted(script, variants, "endpoint-1")
        mock_run.assert_not_called()

    def test_raises_when_script_has_no_shots(self, mocker):
        script = _script(mocker, hook_line="hi", shots=[])
        variants = [_variant(mocker)]
        with pytest.raises(SelfHostedVideoGenerationError, match="no shot data"):
            generate_toon_video_selfhosted(script, variants, "endpoint-1")

    def test_one_workflow_built_per_shot(self, mocker):
        mock_build = mocker.patch(
            "app.media.ltx_workflow.build_workflow",
            side_effect=lambda prompt, duration, **kw: {"prompt": prompt, "duration": duration, **kw},
        )
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))

        script = _script(mocker, hook_line="hi", shots=[
            {"action": "waves", "duration_seconds": 3, "shot_type": "closeup"},
            {"action": "frowns", "duration_seconds": 4, "shot_type": "wide"},
        ])
        variants = [_variant(mocker)]
        result = generate_toon_video_selfhosted(script, variants, "endpoint-1")

        assert result == b"video-bytes"
        assert mock_build.call_count == 2
        sent_shot_workflows = mock_run.call_args.kwargs["shot_workflows"]
        assert len(sent_shot_workflows) == 2
        assert sent_shot_workflows[0]["duration"] == 3
        assert sent_shot_workflows[1]["duration"] == 4
        # Each shot's own photo anchors it — confirmed live 2026-08-29/30:
        # text-to-video with only a LoRA for identity produced held poses,
        # not real animation.
        assert sent_shot_workflows[0]["reference_image_filename"] == "reference.png"
        assert mock_run.call_args.kwargs["shot_reference_images"] == [b"ref-image-bytes", b"ref-image-bytes"]

    def test_each_shot_anchors_on_its_own_speakers_lora_and_photo(self, mocker):
        # Confirmed live 2026-08-30 on a real 3-character script: every
        # shot already carries its own speaker_variant_id — a multi-
        # character script should visually ground EACH shot in that
        # shot's own speaker, not always the primary/first-listed cast
        # member (the old single-continuous-clip limitation).
        mock_build = mocker.patch(
            "app.media.ltx_workflow.build_workflow",
            side_effect=lambda prompt, duration, **kw: {"lora_path": kw.get("lora_path")},
        )
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")

        hans = _variant(mocker, name="Hans", id="hans-id", lora_path="hans.safetensors", image_url="https://x/hans.png")
        wen = _variant(mocker, name="Wen", id="wen-id", lora_path="wen.safetensors", image_url="https://x/wen.png")

        def _fake_get(url, timeout=None):
            return mocker.Mock(content=f"bytes-for-{url}".encode())

        mocker.patch("httpx.get", side_effect=_fake_get)

        script = _script(mocker, hook_line="hi", shots=[
            {"action": "sips tea", "duration_seconds": 3, "speaker_variant_id": "wen-id"},
            {"action": "checks watch", "duration_seconds": 4, "speaker_variant_id": "hans-id"},
        ])
        variants = [hans, wen]
        generate_toon_video_selfhosted(script, variants, "endpoint-1")

        sent_shot_workflows = mock_run.call_args.kwargs["shot_workflows"]
        assert sent_shot_workflows[0]["lora_path"] == "wen.safetensors"
        assert sent_shot_workflows[1]["lora_path"] == "hans.safetensors"
        sent_images = mock_run.call_args.kwargs["shot_reference_images"]
        assert sent_images[0] == b"bytes-for-https://x/wen.png"
        assert sent_images[1] == b"bytes-for-https://x/hans.png"

    def test_reference_image_cached_per_variant_not_refetched_per_shot(self, mocker):
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")
        mock_get = mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))

        script = _script(mocker, hook_line="hi", shots=[
            {"action": "a", "duration_seconds": 3},
            {"action": "b", "duration_seconds": 3},
            {"action": "c", "duration_seconds": 3},
        ])
        variants = [_variant(mocker)]  # same single speaker for every shot
        generate_toon_video_selfhosted(script, variants, "endpoint-1")

        mock_get.assert_called_once()

    def test_use_allocation_retry_routes_through_the_retrying_client_call(self, mocker):
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))
        mock_plain = mocker.patch("app.media.runpod_serverless_client.run_inference_job")
        mock_retry = mocker.patch(
            "app.media.runpod_serverless_client.run_inference_job_with_allocation_retry",
            return_value=b"video-bytes",
        )

        script = _script(mocker, hook_line="hi", shots=[{"action": "waves", "duration_seconds": 3}])
        variants = [_variant(mocker)]
        result = generate_toon_video_selfhosted(script, variants, "endpoint-1", use_allocation_retry=True)

        assert result == b"video-bytes"
        mock_retry.assert_called_once()
        mock_plain.assert_not_called()

    def test_reference_image_fetch_failure_falls_back_to_text_to_video_for_that_shot(self, mocker):
        # Best-effort: a variant whose photo can't be fetched shouldn't
        # fail the whole generation over it.
        mock_build = mocker.patch(
            "app.media.ltx_workflow.build_workflow",
            side_effect=lambda prompt, duration, **kw: {"reference_image_filename": kw.get("reference_image_filename")},
        )
        mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")
        mocker.patch("httpx.get", side_effect=Exception("connection refused"))

        script = _script(mocker, hook_line="hi", shots=[{"action": "waves", "duration_seconds": 3}])
        variants = [_variant(mocker)]
        result = generate_toon_video_selfhosted(script, variants, "endpoint-1")

        assert result == b"video-bytes"
        assert mock_build.call_args.kwargs["reference_image_filename"] is None

    def test_duration_cap_truncates_later_shots_but_always_includes_the_first(self, mocker):
        mock_build = mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))

        script = _script(mocker, hook_line="hi", shots=[
            {"action": "a", "duration_seconds": 5},
            {"action": "b", "duration_seconds": 5},
            {"action": "c", "duration_seconds": 5},
        ])
        variants = [_variant(mocker)]
        generate_toon_video_selfhosted(script, variants, "endpoint-1", duration_seconds=8)

        # 5s (shot 1) included; shot 2 would push cumulative to 10s > 8s cap.
        assert mock_build.call_count == 1
        assert len(mock_run.call_args.kwargs["shot_workflows"]) == 1

    def test_no_cap_includes_every_shot(self, mocker):
        mock_build = mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))

        script = _script(mocker, hook_line="hi", shots=[
            {"action": "a", "duration_seconds": 5},
            {"action": "b", "duration_seconds": 5},
            {"action": "c", "duration_seconds": 5},
        ])
        variants = [_variant(mocker)]
        generate_toon_video_selfhosted(script, variants, "endpoint-1")

        assert mock_build.call_count == 3

    def test_shot_missing_duration_falls_back_to_default(self, mocker):
        mock_build = mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))

        script = _script(mocker, hook_line="hi", shots=[{"action": "waves"}])
        variants = [_variant(mocker)]
        generate_toon_video_selfhosted(script, variants, "endpoint-1")

        assert mock_build.call_args.args[1] == 3  # _DEFAULT_SHOT_DURATION_SECONDS

    def test_dialogue_sends_narration_text_for_on_worker_chatterbox_synthesis(self, mocker):
        # This pipeline generated silent video only before ElevenLabs/
        # Chatterbox support — confirms the default (no ElevenLabs
        # configured) path sends raw dialogue TEXT for the RunPod worker's
        # own GPU to synthesize via Chatterbox, not pre-synthesized bytes.
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-with-audio")

        script = _script(mocker, hook_line="hi", shots=[
            {"action": "waves", "duration_seconds": 3, "dialogue": "Hello there"},
        ])
        variants = [_variant(mocker)]
        result = generate_toon_video_selfhosted(script, variants, "endpoint-1")

        assert result == b"video-with-audio"
        assert mock_run.call_args.kwargs["narration_text"] == "Hello there"
        assert mock_run.call_args.kwargs["narration_audio_bytes"] is None

    def test_no_dialogue_sends_no_narration_at_all(self, mocker):
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"silent-video-bytes")

        script = _script(mocker, hook_line="hi", shots=[
            {"action": "waves", "duration_seconds": 3, "dialogue": None},
        ])
        variants = [_variant(mocker)]
        result = generate_toon_video_selfhosted(script, variants, "endpoint-1")

        assert result == b"silent-video-bytes"
        assert mock_run.call_args.kwargs["narration_audio_bytes"] is None
        assert mock_run.call_args.kwargs["narration_text"] is None

    def test_elevenlabs_configured_sends_pre_synthesized_audio_bytes(self, mocker):
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-with-audio")
        mocker.patch(
            "app.services.culturetoon_selfhosted_video._synthesize_narration_elevenlabs",
            return_value=b"elevenlabs-bytes",
        )

        script = _script(mocker, hook_line="hi", shots=[
            {"action": "waves", "duration_seconds": 3, "dialogue": "Hello there"},
        ])
        variants = [_variant(mocker, voice_provider="elevenlabs", elevenlabs_voice_id="voice-1")]
        result = generate_toon_video_selfhosted(script, variants, "endpoint-1", elevenlabs_api_key="sk-key")

        assert result == b"video-with-audio"
        assert mock_run.call_args.kwargs["narration_audio_bytes"] == b"elevenlabs-bytes"
        assert mock_run.call_args.kwargs["narration_text"] is None

    def test_timeout_scales_with_shot_count(self, mocker):
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))

        script = _script(mocker, hook_line="hi", shots=[
            {"action": "a", "duration_seconds": 3},
            {"action": "b", "duration_seconds": 3},
            {"action": "c", "duration_seconds": 3},
        ])
        variants = [_variant(mocker)]
        generate_toon_video_selfhosted(script, variants, "endpoint-1")

        # floor is 1200s — 3 shots * 400s/shot + 300s = 1500s, above the floor.
        assert mock_run.call_args.kwargs["timeout_seconds"] == 1500

    def test_timeout_floor_applies_for_a_single_shot(self, mocker):
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))

        script = _script(mocker, hook_line="hi", shots=[{"action": "a", "duration_seconds": 3}])
        variants = [_variant(mocker)]
        generate_toon_video_selfhosted(script, variants, "endpoint-1")

        assert mock_run.call_args.kwargs["timeout_seconds"] == 1200


_SHOTS = [{"shot_number": 1, "duration_seconds": 4, "action": "waves", "expression": "Happy", "dialogue": None}]


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        CharacterBrand.__table__, Character.__table__, CharacterVariant.__table__,
        ToonScript.__table__, Toon.__table__, GenerationUsage.__table__,
        ToonBackground.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


@pytest.fixture
def seeded(db):
    session = db()
    user_id = uuid.uuid4()
    brand = CharacterBrand(user_id=user_id, name="Test Brand")
    session.add(brand)
    session.commit()

    character = Character(brand_id=brand.id, name="Base")
    session.add(character)
    session.commit()

    variant = CharacterVariant(
        character_id=character.id, name="Mom", image_url="https://img/mom.png",
        lora_status="ready", lora_path="mom.safetensors",
    )
    session.add(variant)
    session.commit()

    script = ToonScript(brand_id=brand.id, character_variant_id=variant.id, shots=_SHOTS, total_duration_seconds=8)
    session.add(script)
    session.commit()

    toon = Toon(brand_id=brand.id, character_variant_id=variant.id, script_id=script.id, status="animating")
    session.add(toon)
    session.commit()

    ids = {"user_id": str(user_id), "brand_id": str(brand.id), "toon_id": str(toon.id), "variant_id": str(variant.id)}
    session.close()
    return ids


class TestGenerateVideoForToonSelfhosted:
    def test_success_path(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("app.media.runpod_serverless_client.run_inference_job_with_allocation_retry", return_value=b"video-bytes")
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "ready"
        assert toon.video_provider == "self_hosted"
        assert toon.raw_video_url == "https://supabase/video.mp4"
        assert toon.final_video_url == "https://supabase/video.mp4"
        mock_upload.assert_called_once()

        usage = session.query(GenerationUsage).filter_by(toon_id=uuid.UUID(seeded["toon_id"])).all()
        assert len(usage) == 1
        assert usage[0].provider == "runpod_ltx"

    def test_regenerating_archives_the_previous_take(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("app.media.runpod_serverless_client.run_inference_job_with_allocation_retry", return_value=b"take-2")
        mocker.patch("app.media.storage.upload", return_value="https://supabase/take-2.mp4")

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        toon.raw_video_url = "https://supabase/take-1.mp4"
        toon.final_video_url = "https://supabase/take-1.mp4"
        session.commit()
        session.close()

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.final_video_url == "https://supabase/take-2.mp4"
        assert toon.previous_video_urls == ["https://supabase/take-1.mp4"]

    def test_missing_endpoint_id_marks_toon_failed(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {}, clear=False)
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": ""})
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job_with_allocation_retry")

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "RUNPOD_SERVERLESS_ENDPOINT_ID" in toon.generation_error
        mock_run.assert_not_called()

    def test_lora_not_ready_marks_toon_failed_and_still_records_usage(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        session = db()
        variant = session.query(CharacterVariant).filter_by(id=uuid.UUID(seeded["variant_id"])).first()
        variant.lora_status = "training"
        session.commit()
        session.close()

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "trained LoRA" in toon.generation_error
        # A failed generation still gets a usage row recorded (same
        # philosophy as the batch runner) — cost is 0-duration here since
        # generation never actually started, but the row itself exists.
        usage = session.query(GenerationUsage).filter_by(toon_id=uuid.UUID(seeded["toon_id"])).all()
        assert len(usage) == 1

    def test_runpod_failure_marks_toon_failed(self, db, seeded, mocker):
        from app.media.runpod_serverless_client import RunPodServerlessError
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch(
            "app.media.runpod_serverless_client.run_inference_job_with_allocation_retry",
            side_effect=RunPodServerlessError("worker allocation timed out"),
        )

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "worker allocation timed out" in toon.generation_error

    def test_stale_connection_on_the_failure_commit_does_not_leave_toon_stuck_animating(self, db, seeded, mocker):
        """Confirmed live 2026-08-26, twice in a row: a RunPod allocation
        failure's own commit() (writing status='failed') hit a stale
        Postgres connection after the long allocation-retry wait and raised
        its own OperationalError, masking the original failure and leaving
        the Toon stuck at status='animating' forever. _resilient_commit
        should retry past exactly this and still land status='failed'."""
        from app.media.runpod_serverless_client import RunPodServerlessError
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch(
            "app.media.runpod_serverless_client.run_inference_job_with_allocation_retry",
            side_effect=RunPodServerlessError("worker allocation timed out"),
        )
        # Call 1 is the early status='animating' write (before RunPod even
        # runs) — must succeed so the flow actually reaches the RunPod
        # failure. Call 2 is the failure-commit this test targets: the
        # first attempt inside _resilient_commit, right after the
        # RunPodServerlessError — this is the one confirmed live to hit a
        # stale connection.
        real_commit = __import__("sqlalchemy").orm.Session.commit
        call_count = {"n": 0}

        def flaky_commit(self):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise Exception("server closed the connection unexpectedly")
            return real_commit(self)

        mocker.patch("sqlalchemy.orm.Session.commit", flaky_commit)

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "worker allocation timed out" in toon.generation_error

    def test_scripts_own_background_id_is_fetched_and_passed_through(self, db, seeded, mocker):
        # Confirmed live 2026-08-30: neither Toon.background_id nor
        # ToonScript.background_id was ever read by this path at all, so a
        # selected Location never reached the video prompt. The script's
        # own background_id wins over the toon's per that column's own
        # docstring ("a script's setting drives its background").
        session = db()
        script_background = ToonBackground(brand_id=uuid.UUID(seeded["brand_id"]), name="Diner", description="A 1950s American diner")
        toon_background = ToonBackground(brand_id=uuid.UUID(seeded["brand_id"]), name="Office", description="A cramped cubicle")
        session.add_all([script_background, toon_background])
        session.commit()
        script = session.query(ToonScript).first()
        script.background_id = script_background.id
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        toon.background_id = toon_background.id
        session.commit()
        session.close()

        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.runpod_serverless_client.run_inference_job_with_allocation_retry", return_value=b"video-bytes")
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")
        # The queried ToonBackground is bound to a session that
        # generate_video_for_toon_selfhosted opens and closes internally —
        # capture the field we care about at call time via side_effect,
        # rather than inspecting the (by-then-detached) object afterward.
        seen_names = []

        def _capture(script, background=None):
            seen_names.append(background.name if background is not None else None)
            return "a prompt"

        mocker.patch(
            "app.services.culturetoon_selfhosted_video._build_shot_prompt", side_effect=_capture,
        )
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        assert seen_names == ["Diner"]

    def test_falls_back_to_toons_background_id_when_script_has_none(self, db, seeded, mocker):
        session = db()
        toon_background = ToonBackground(brand_id=uuid.UUID(seeded["brand_id"]), name="Office", description="A cramped cubicle")
        session.add(toon_background)
        session.commit()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        toon.background_id = toon_background.id
        session.commit()
        session.close()

        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.runpod_serverless_client.run_inference_job_with_allocation_retry", return_value=b"video-bytes")
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")
        seen_names = []

        def _capture(script, background=None):
            seen_names.append(background.name if background is not None else None)
            return "a prompt"

        mocker.patch(
            "app.services.culturetoon_selfhosted_video._build_shot_prompt", side_effect=_capture,
        )
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        assert seen_names == ["Office"]

    def test_neither_script_nor_toon_has_a_background_passes_none(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.runpod_serverless_client.run_inference_job_with_allocation_retry", return_value=b"video-bytes")
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")
        mock_build_prompt = mocker.patch(
            "app.services.culturetoon_selfhosted_video._build_shot_prompt", return_value="a prompt",
        )
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("httpx.get", return_value=mocker.Mock(content=b"ref-image-bytes"))

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        assert mock_build_prompt.call_args.kwargs["background"] is None

    def test_no_elevenlabs_key_configured_falls_back_to_edge_tts(self, db, seeded, mocker):
        session = db()
        variant = session.query(CharacterVariant).filter_by(id=uuid.UUID(seeded["variant_id"])).first()
        variant.voice_provider = "elevenlabs"
        variant.elevenlabs_voice_id = "voice-1"
        session.commit()
        session.close()

        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")
        mock_generate = mocker.patch(
            "app.services.culturetoon_selfhosted_video.generate_toon_video_selfhosted",
            return_value=b"video-bytes",
        )

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        # Brand has no elevenlabs_api_key_encrypted set -> voice_provider
        # opt-in alone isn't enough, same fail-open philosophy as the
        # Kling path's own ElevenLabs handling.
        assert mock_generate.call_args.kwargs["elevenlabs_api_key"] is None

    def test_elevenlabs_key_configured_is_decrypted_and_passed_through(self, db, seeded, mocker):
        from app.social.crypto import encrypt

        session = db()
        brand = session.query(CharacterBrand).filter_by(id=uuid.UUID(seeded["brand_id"])).first()
        brand.elevenlabs_api_key_encrypted = encrypt("sk-real-key")
        variant = session.query(CharacterVariant).filter_by(id=uuid.UUID(seeded["variant_id"])).first()
        variant.voice_provider = "elevenlabs"
        variant.elevenlabs_voice_id = "voice-1"
        session.commit()
        session.close()

        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")
        mock_generate = mocker.patch(
            "app.services.culturetoon_selfhosted_video.generate_toon_video_selfhosted",
            return_value=b"video-bytes",
        )

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        assert mock_generate.call_args.kwargs["elevenlabs_api_key"] == "sk-real-key"

    def test_voice_provider_kling_never_resolves_an_elevenlabs_key(self, db, seeded, mocker):
        # variant.voice_provider defaults to "kling" in the seeded fixture —
        # confirms the brand's elevenlabs_api_key_encrypted column is never
        # even queried/decrypted when the variant hasn't opted in.
        from app.social.crypto import encrypt

        session = db()
        brand = session.query(CharacterBrand).filter_by(id=uuid.UUID(seeded["brand_id"])).first()
        brand.elevenlabs_api_key_encrypted = encrypt("sk-real-key")
        session.commit()
        session.close()

        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")
        mock_generate = mocker.patch(
            "app.services.culturetoon_selfhosted_video.generate_toon_video_selfhosted",
            return_value=b"video-bytes",
        )

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        assert mock_generate.call_args.kwargs["elevenlabs_api_key"] is None

    def test_resilient_commit_raises_after_exhausting_retries(self, mocker):
        session = mocker.Mock()
        session.commit.side_effect = Exception("still dead")
        mutate = mocker.Mock()

        with pytest.raises(Exception, match="still dead"):
            _resilient_commit(session, mutate)

        assert session.rollback.call_count == session.commit.call_count
        # mutate must be re-run on every attempt, not just the first — a
        # rollback expires/discards whatever it set the first time.
        assert mutate.call_count == session.commit.call_count

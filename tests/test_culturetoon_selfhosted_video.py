"""Tests for app/services/culturetoon_selfhosted_video.py — prompt building
from a ToonScript's shots and the cast LoRA-readiness gate."""
import pytest

from app.services.culturetoon_selfhosted_video import (
    build_prompt_from_script, resolve_ready_lora, generate_toon_video_selfhosted,
    SelfHostedVideoGenerationError,
)


def _script(mocker, hook_line=None, shots=None, total_duration_seconds=None):
    s = mocker.Mock()
    s.hook_line = hook_line
    s.shots = shots or []
    s.total_duration_seconds = total_duration_seconds
    return s


def _variant(mocker, name="Kumar", lora_status="ready", lora_path="loras/kumar.safetensors"):
    v = mocker.Mock()
    v.name = name
    v.lora_status = lora_status
    v.lora_path = lora_path
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

    def test_no_content_falls_back_to_generic_prompt(self, mocker):
        script = _script(mocker, hook_line=None, shots=[])
        assert build_prompt_from_script(script) == "A character reacts to their day."


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


class TestGenerateToonVideoSelfhosted:
    def test_raises_before_calling_runpod_when_cast_not_ready(self, mocker):
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job")
        script = _script(mocker, hook_line="hi", shots=[])
        variants = [_variant(mocker, lora_status="none")]
        with pytest.raises(SelfHostedVideoGenerationError):
            generate_toon_video_selfhosted(script, variants, "endpoint-1")
        mock_run.assert_not_called()

    def test_full_success_path(self, mocker):
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")

        script = _script(mocker, hook_line="hi", shots=[], total_duration_seconds=8)
        variants = [_variant(mocker)]
        result = generate_toon_video_selfhosted(script, variants, "endpoint-1")
        assert result == b"video-bytes"
        mock_run.assert_called_once_with("endpoint-1", {"1": {}})

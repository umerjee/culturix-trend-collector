"""Tests for app/services/culturetoon_lora.py — LoRA training bookkeeping
and the remote-training orchestration, mocked at the runpod_client/
runpod_ssh/storage boundary (paramiko/RunPod's real API are never touched)."""
import pytest

from app.services.culturetoon_lora import (
    add_training_images, train_character_lora, MIN_LORA_TRAINING_IMAGES, LoraTrainingError,
)


def _variant(mocker, name="Kumar", training_images=None):
    v = mocker.Mock()
    v.id = "variant-1"
    v.name = name
    v.lora_training_image_urls = training_images
    v.lora_status = "none"
    v.lora_path = None
    return v


class TestAddTrainingImages:
    def test_appends_to_empty_list(self, mocker):
        variant = _variant(mocker, training_images=None)
        add_training_images(variant, ["url1", "url2"])
        assert variant.lora_training_image_urls == ["url1", "url2"]

    def test_appends_to_existing_list(self, mocker):
        variant = _variant(mocker, training_images=["url1"])
        add_training_images(variant, ["url2", "url3"])
        assert variant.lora_training_image_urls == ["url1", "url2", "url3"]


class TestTrainCharacterLora:
    def _mock_success(self, mocker):
        mocker.patch("app.media.runpod_client.start_pod")
        mocker.patch("app.media.runpod_client.wait_for_pod_ready")
        mock_stop = mocker.patch("app.media.runpod_client.stop_pod")
        mocker.patch("app.media.runpod_client.get_pod_ssh_info", return_value=("1.2.3.4", 2222))
        mock_run = mocker.patch("app.media.runpod_ssh.run_remote_command", return_value=(0, "", ""))
        mocker.patch("app.media.runpod_ssh.download_file", return_value=b"lora-bytes")
        mocker.patch("app.media.storage.upload", return_value="https://example.com/kumar.safetensors")
        return mock_stop, mock_run

    def test_too_few_images_raises_without_starting_pod(self, mocker):
        mock_start = mocker.patch("app.media.runpod_client.start_pod")
        variant = _variant(mocker, training_images=["url1", "url2"])
        with pytest.raises(LoraTrainingError, match=str(MIN_LORA_TRAINING_IMAGES)):
            train_character_lora(variant)
        mock_start.assert_not_called()
        assert variant.lora_status == "none"  # unchanged — never even attempted

    def test_success_sets_lora_path_and_ready_status(self, mocker):
        self._mock_success(mocker)
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        train_character_lora(variant)

        assert variant.lora_status == "ready"
        assert variant.lora_path == "https://example.com/kumar.safetensors"

    def test_pod_stopped_even_on_success(self, mocker, monkeypatch):
        monkeypatch.setenv("RUNPOD_POD_ID", "pod-123")
        mock_stop, _ = self._mock_success(mocker)
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])
        train_character_lora(variant)
        mock_stop.assert_called_once()

    def test_pod_stopped_even_on_failure(self, mocker, monkeypatch):
        monkeypatch.setenv("RUNPOD_POD_ID", "pod-123")
        mocker.patch("app.media.runpod_client.start_pod")
        mocker.patch("app.media.runpod_client.wait_for_pod_ready", side_effect=RuntimeError("boom"))
        mock_stop = mocker.patch("app.media.runpod_client.stop_pod")
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        with pytest.raises(LoraTrainingError):
            train_character_lora(variant)

        mock_stop.assert_called_once()
        assert variant.lora_status == "failed"

    def test_training_command_failure_sets_failed_status(self, mocker):
        mocker.patch("app.media.runpod_client.start_pod")
        mocker.patch("app.media.runpod_client.wait_for_pod_ready")
        mocker.patch("app.media.runpod_client.stop_pod")
        mocker.patch("app.media.runpod_client.get_pod_ssh_info", return_value=("1.2.3.4", 2222))
        # First call (staging images) succeeds, second (ltx-trainer) fails.
        mocker.patch(
            "app.media.runpod_ssh.run_remote_command",
            side_effect=[(0, "", ""), (1, "", "CUDA out of memory")],
        )
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        with pytest.raises(LoraTrainingError, match="CUDA out of memory"):
            train_character_lora(variant)

        assert variant.lora_status == "failed"

    def test_image_staging_failure_sets_failed_status(self, mocker):
        mocker.patch("app.media.runpod_client.start_pod")
        mocker.patch("app.media.runpod_client.wait_for_pod_ready")
        mocker.patch("app.media.runpod_client.stop_pod")
        mocker.patch("app.media.runpod_client.get_pod_ssh_info", return_value=("1.2.3.4", 2222))
        mocker.patch("app.media.runpod_ssh.run_remote_command", return_value=(1, "", "curl: 404"))
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        with pytest.raises(LoraTrainingError):
            train_character_lora(variant)

        assert variant.lora_status == "failed"

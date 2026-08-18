"""Tests for app/services/culturetoon_lora.py — LoRA training bookkeeping
and the remote-training orchestration against an ephemeral training pod,
mocked at the runpod_client/runpod_ssh/runpod_s3 boundary (paramiko/
boto3/RunPod's real APIs are never touched)."""
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
        mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mock_terminate = mocker.patch("app.media.runpod_client.terminate_pod")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", return_value=("1.2.3.4", 2222))
        # Two successful remote commands, in order: stage images, run
        # ltx-trainer. The trained file is then SFTP-downloaded and pushed
        # to the volume via S3, not verified over SSH anymore.
        mock_run = mocker.patch(
            "app.media.runpod_ssh.run_remote_command",
            side_effect=[(0, "", ""), (0, "", "")],
        )
        mocker.patch("app.media.runpod_ssh.download_file", return_value=b"lora-bytes")
        mock_upload = mocker.patch("app.media.runpod_s3.upload_lora")
        mocker.patch("app.media.runpod_s3.verify_exists", return_value=True)
        return mock_terminate, mock_run, mock_upload

    def test_too_few_images_raises_without_creating_a_pod(self, mocker):
        mock_create = mocker.patch("app.media.runpod_client.create_training_pod")
        variant = _variant(mocker, training_images=["url1", "url2"])
        with pytest.raises(LoraTrainingError, match=str(MIN_LORA_TRAINING_IMAGES)):
            train_character_lora(variant)
        mock_create.assert_not_called()
        assert variant.lora_status == "none"  # unchanged — never even attempted

    def test_success_sets_lora_path_to_bare_filename_and_ready_status(self, mocker):
        self._mock_success(mocker)
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        train_character_lora(variant)

        assert variant.lora_status == "ready"
        # A bare filename resolvable by ComfyUI's LoraLoader relative to the
        # Network Volume's models/loras/ dir — not a URL, even though the
        # file passes through this backend on its way there via SFTP+S3.
        assert variant.lora_path == "variant-1.safetensors"

    def test_uploads_downloaded_bytes_to_the_expected_volume_key(self, mocker):
        _, _, mock_upload = self._mock_success(mocker)
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        train_character_lora(variant)

        mock_upload.assert_called_once_with(b"lora-bytes", "ComfyUI/models/loras/variant-1.safetensors")

    def test_pod_created_and_terminated_on_success(self, mocker):
        mock_terminate, _, _ = self._mock_success(mocker)
        mock_create = mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", return_value=("1.2.3.4", 2222))
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        train_character_lora(variant)

        mock_create.assert_called_once()
        mock_terminate.assert_called_once_with("pod-123")

    def test_pod_terminated_even_on_failure(self, mocker):
        mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", side_effect=RuntimeError("boom"))
        mock_terminate = mocker.patch("app.media.runpod_client.terminate_pod")
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        with pytest.raises(LoraTrainingError):
            train_character_lora(variant)

        mock_terminate.assert_called_once_with("pod-123")
        assert variant.lora_status == "failed"

    def test_no_pod_created_means_no_termination_attempt(self, mocker):
        # too-few-images case: fails before create_training_pod is ever
        # called, so there's no pod id to terminate.
        mock_terminate = mocker.patch("app.media.runpod_client.terminate_pod")
        variant = _variant(mocker, training_images=["url1"])
        with pytest.raises(LoraTrainingError):
            train_character_lora(variant)
        mock_terminate.assert_not_called()

    def test_training_command_failure_sets_failed_status(self, mocker):
        mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mocker.patch("app.media.runpod_client.terminate_pod")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", return_value=("1.2.3.4", 2222))
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
        mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mocker.patch("app.media.runpod_client.terminate_pod")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", return_value=("1.2.3.4", 2222))
        mocker.patch("app.media.runpod_ssh.run_remote_command", return_value=(1, "", "curl: 404"))
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        with pytest.raises(LoraTrainingError):
            train_character_lora(variant)

        assert variant.lora_status == "failed"

    def test_s3_upload_failure_sets_failed_status(self, mocker):
        from app.media.runpod_s3 import RunPodS3Error

        mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mocker.patch("app.media.runpod_client.terminate_pod")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", return_value=("1.2.3.4", 2222))
        mocker.patch(
            "app.media.runpod_ssh.run_remote_command", side_effect=[(0, "", ""), (0, "", "")],
        )
        mocker.patch("app.media.runpod_ssh.download_file", return_value=b"lora-bytes")
        mocker.patch("app.media.runpod_s3.upload_lora", side_effect=RunPodS3Error("connection refused"))
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        with pytest.raises(LoraTrainingError, match="connection refused"):
            train_character_lora(variant)

        assert variant.lora_status == "failed"

    def test_s3_verify_failure_after_upload_sets_failed_status(self, mocker):
        mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mocker.patch("app.media.runpod_client.terminate_pod")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", return_value=("1.2.3.4", 2222))
        mocker.patch(
            "app.media.runpod_ssh.run_remote_command", side_effect=[(0, "", ""), (0, "", "")],
        )
        mocker.patch("app.media.runpod_ssh.download_file", return_value=b"lora-bytes")
        mocker.patch("app.media.runpod_s3.upload_lora")
        mocker.patch("app.media.runpod_s3.verify_exists", return_value=False)
        variant = _variant(mocker, training_images=[f"url{i}" for i in range(MIN_LORA_TRAINING_IMAGES)])

        with pytest.raises(LoraTrainingError, match="Network Volume"):
            train_character_lora(variant)

        assert variant.lora_status == "failed"

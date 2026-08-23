"""Tests for app/services/culturetoon_lora.py — training-image captioning,
Culturix's own auto-curation of the training set, LoRA training bookkeeping,
and the remote-training orchestration against an ephemeral training pod,
mocked at the runpod_client/runpod_ssh/runpod_s3 boundary (paramiko/
boto3/RunPod's real APIs are never touched)."""
import uuid

import pytest

from app.services.culturetoon_lora import (
    add_training_images, caption_training_image, curate_training_images,
    train_character_lora, MIN_LORA_TRAINING_IMAGES, LoraTrainingError,
)

_VARIANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_FOUND_CHECKPOINT = f"/workspace/lora_training/{_VARIANT_ID}/output/checkpoints/lora_weights_step_001000.safetensors"


def _variant(mocker, name="Kumar", training_images=None, image_url=None):
    v = mocker.Mock()
    v.id = _VARIANT_ID
    v.name = name
    v.image_url = image_url
    v.lora_training_images = training_images
    v.lora_status = "none"
    v.lora_path = None
    return v


def _expression(mocker, name, image_url):
    e = mocker.Mock()
    e.name = name
    e.image_url = image_url
    return e


def _fake_session(mocker, expressions):
    """A minimal session stand-in for curate_training_images()'s
    session.query(Expression).filter_by(...).order_by(...).all() chain."""
    session = mocker.Mock()
    query = mocker.Mock()
    session.query.return_value = query
    query.filter_by.return_value = query
    query.order_by.return_value = query
    query.all.return_value = expressions
    return session


def _train(mocker, variant):
    """TestTrainCharacterLora's own tests exercise orchestration, not
    curation (which has its own dedicated TestCurateTrainingImages) — so
    curate_training_images is patched to just surface whatever the fixture
    variant's lora_training_images already holds, and a bare Mock stands
    in for the session param (train_character_lora only threads it through
    to curate_training_images, which is patched out here)."""
    mocker.patch(
        "app.services.culturetoon_lora.curate_training_images",
        return_value=variant.lora_training_images or [],
    )
    return train_character_lora(variant, mocker.Mock())


def _entries(n, captioned=True):
    return [
        {"url": f"url{i}", "caption": f"Kumar waving, shot {i}" if captioned else ""}
        for i in range(n)
    ]


def _fake_run_remote_command(fail_on_substring=None, fail_result=(1, "", "boom")):
    """Builds a run_remote_command side_effect that succeeds for every step
    except one identified by a substring of the command (e.g. "ffmpeg" or
    "process_dataset.py"), and always answers the final "find the trained
    checkpoint" `ls` lookup with a realistic path so later steps (SFTP
    download, S3 push) have something to act on.

    Training itself (scripts/train.py) runs backgrounded (nohup) and is
    polled via separate kill -0/status-file/log-tail commands rather than
    one blocking call — see _run_training_backgrounded — so a simulated
    training failure (fail_on_substring="scripts/train.py") surfaces
    through THOSE commands, not the script-launch commands (which always
    succeed instantly; they just start a background process). The launch
    script's heredoc body embeds the real train_cmd text verbatim
    (including the substring "scripts/train.py"), so heredoc writes are
    special-cased to always succeed regardless of fail_on_substring —
    otherwise a "scripts/train.py" failure would be misattributed to
    writing the launch script instead of the simulated training run."""
    def fake(host, port, command, timeout_seconds=1800):
        first_line = command.split("\n", 1)[0].strip()
        if first_line.startswith("cat > "):
            return (0, "", "")
        if first_line.endswith("& echo $!"):
            return (0, "12345\n", "")
        if first_line.startswith("kill -0"):
            return (0, "DEAD\n", "")
        if first_line.startswith("cat ") and "train.status" in first_line:
            return (0, "EXIT:1\n" if fail_on_substring == "scripts/train.py" else "EXIT:0\n", "")
        if first_line.startswith("tail") and "train.log" in first_line:
            return (0, fail_result[2] if fail_on_substring == "scripts/train.py" else "", "")
        if fail_on_substring and fail_on_substring in command:
            return fail_result
        if first_line.startswith("ls -1") and "lora_weights_step_" in first_line:
            return (0, f"{_FOUND_CHECKPOINT}\n", "")
        return (0, "", "")
    return fake


class TestCaptionTrainingImage:
    def _fake_qwen_response(self, mocker, text):
        message = mocker.Mock()
        message.content = text
        choice = mocker.Mock()
        choice.message = message
        response = mocker.Mock()
        response.choices = [choice]
        return response

    def test_uses_qwen_vision_when_available(self, mocker, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "test-key")
        client = mocker.Mock()
        client.chat.completions.create.return_value = self._fake_qwen_response(mocker, "Kumar smiling in a kitchen")
        mocker.patch("openai.OpenAI", return_value=client)

        caption = caption_training_image("https://example.com/img.png", "Kumar")

        assert caption == "Kumar smiling in a kitchen"
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "qwen-vl-max"
        content = call_kwargs["messages"][0]["content"]
        assert content[0] == {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}}

    def test_falls_back_to_claude_vision_when_no_qwen_key(self, mocker, monkeypatch):
        monkeypatch.delenv("QWEN_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mocker.patch("httpx.get", return_value=mocker.Mock(
            content=b"fake-bytes", headers={"content-type": "image/png"}, raise_for_status=mocker.Mock(),
        ))
        text_block = mocker.Mock()
        text_block.text = "Kumar waving on a rooftop"
        message = mocker.Mock()
        message.content = [text_block]
        client = mocker.Mock()
        client.messages.create.return_value = message
        mocker.patch("anthropic.Anthropic", return_value=client)

        caption = caption_training_image("https://example.com/img.png", "Kumar")

        assert caption == "Kumar waving on a rooftop"
        assert client.messages.create.call_args.kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_falls_back_to_bare_name_on_any_error(self, mocker, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "test-key")
        mocker.patch("openai.OpenAI", side_effect=RuntimeError("rate limited"))

        caption = caption_training_image("https://example.com/img.png", "Kumar")

        assert caption == "Kumar"

    def test_empty_model_response_falls_back_to_bare_name(self, mocker, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "test-key")
        client = mocker.Mock()
        client.chat.completions.create.return_value = self._fake_qwen_response(mocker, "")
        mocker.patch("openai.OpenAI", return_value=client)

        assert caption_training_image("https://example.com/img.png", "Kumar") == "Kumar"


class TestAddTrainingImages:
    def test_appends_to_empty_list_with_per_image_captions(self, mocker):
        mocker.patch("app.services.culturetoon_lora.caption_training_image", side_effect=lambda url, name: f"{name} at {url}")
        variant = _variant(mocker, training_images=None)

        add_training_images(variant, ["url1", "url2"])

        assert variant.lora_training_images == [
            {"url": "url1", "caption": "Kumar at url1"},
            {"url": "url2", "caption": "Kumar at url2"},
        ]

    def test_appends_to_existing_list(self, mocker):
        mocker.patch("app.services.culturetoon_lora.caption_training_image", return_value="a caption")
        variant = _variant(mocker, training_images=[{"url": "url1", "caption": "existing"}])

        add_training_images(variant, ["url2"])

        assert variant.lora_training_images == [
            {"url": "url1", "caption": "existing"},
            {"url": "url2", "caption": "a caption"},
        ]

    def test_captioning_failure_for_one_image_does_not_block_the_others(self, mocker):
        # caption_training_image itself fails open (see TestCaptionTrainingImage) —
        # this just confirms add_training_images doesn't add its own
        # try/except on top that could double-swallow or re-raise.
        mocker.patch("app.services.culturetoon_lora.caption_training_image", return_value="Kumar")
        variant = _variant(mocker, training_images=None)

        add_training_images(variant, ["url1", "url2"])

        assert len(variant.lora_training_images) == 2
        assert all(e["caption"] == "Kumar" for e in variant.lora_training_images)


class TestCurateTrainingImages:
    def test_builds_entries_from_portrait_and_expressions_with_deterministic_captions(self, mocker):
        variant = _variant(mocker, image_url="https://example.com/portrait.png")
        expressions = [
            _expression(mocker, "Happy", "https://example.com/happy.png"),
            _expression(mocker, "Angry", "https://example.com/angry.png"),
        ]
        session = _fake_session(mocker, expressions)

        entries = curate_training_images(session, variant)

        assert entries == [
            {"url": "https://example.com/portrait.png", "caption": "Kumar, neutral reference pose"},
            {"url": "https://example.com/happy.png", "caption": "Kumar, happy expression"},
            {"url": "https://example.com/angry.png", "caption": "Kumar, angry expression"},
        ]

    def test_skips_expressions_with_no_image_yet(self, mocker):
        variant = _variant(mocker, image_url=None)
        expressions = [
            _expression(mocker, "Happy", "https://example.com/happy.png"),
            _expression(mocker, "Angry", None),  # not generated yet
        ]
        session = _fake_session(mocker, expressions)

        entries = curate_training_images(session, variant)

        assert len(entries) == 1
        assert entries[0]["url"] == "https://example.com/happy.png"

    def test_merges_manual_supplemental_entries_keeping_their_own_captions(self, mocker):
        variant = _variant(
            mocker, image_url="https://example.com/portrait.png",
            training_images=[{"url": "https://example.com/manual.png", "caption": "a real photo, outdoors"}],
        )
        session = _fake_session(mocker, [])

        entries = curate_training_images(session, variant)

        assert {"url": "https://example.com/manual.png", "caption": "a real photo, outdoors"} in entries

    def test_deduplicates_by_url_preferring_the_curated_caption(self, mocker):
        # A manual upload that happens to be the same URL as the portrait
        # (e.g. re-added) shouldn't produce two training-set entries.
        variant = _variant(
            mocker, image_url="https://example.com/portrait.png",
            training_images=[{"url": "https://example.com/portrait.png", "caption": "manual caption"}],
        )
        session = _fake_session(mocker, [])

        entries = curate_training_images(session, variant)

        assert len(entries) == 1
        assert entries[0]["caption"] == "Kumar, neutral reference pose"

    def test_empty_when_nothing_generated_or_uploaded_yet(self, mocker):
        variant = _variant(mocker, image_url=None, training_images=None)
        session = _fake_session(mocker, [])

        assert curate_training_images(session, variant) == []


class TestTrainCharacterLora:
    def _mock_success(self, mocker, fail_on_substring=None, fail_result=(1, "", "boom")):
        mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mock_terminate = mocker.patch("app.media.runpod_client.terminate_pod")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", return_value=("1.2.3.4", 2222))
        mock_run = mocker.patch(
            "app.media.runpod_ssh.run_remote_command",
            side_effect=_fake_run_remote_command(fail_on_substring, fail_result),
        )
        mocker.patch("app.media.runpod_ssh.download_file", return_value=b"lora-bytes")
        mock_upload = mocker.patch("app.media.runpod_s3.upload_lora")
        mocker.patch("app.media.runpod_s3.verify_exists", return_value=True)
        return mock_terminate, mock_run, mock_upload

    def _training_variant(self, mocker, captioned=True):
        return _variant(mocker, training_images=_entries(MIN_LORA_TRAINING_IMAGES, captioned=captioned))

    def test_too_few_images_raises_without_creating_a_pod(self, mocker):
        mock_create = mocker.patch("app.media.runpod_client.create_training_pod")
        variant = _variant(mocker, training_images=_entries(2))
        with pytest.raises(LoraTrainingError, match=str(MIN_LORA_TRAINING_IMAGES)):
            _train(mocker, variant)
        mock_create.assert_not_called()
        assert variant.lora_status == "none"  # unchanged — never even attempted

    def test_success_sets_lora_path_to_bare_filename_and_ready_status(self, mocker):
        self._mock_success(mocker)
        variant = self._training_variant(mocker)

        _train(mocker, variant)

        assert variant.lora_status == "ready"
        # A bare filename resolvable by ComfyUI's LoraLoaderModelOnly
        # relative to the Network Volume's models/loras/ dir — not a URL,
        # even though the file passes through this backend on its way
        # there via SFTP+S3.
        assert variant.lora_path == f"{_VARIANT_ID}.safetensors"

    def test_uses_each_image_own_caption_in_the_dataset_manifest(self, mocker):
        _, mock_run, _ = self._mock_success(mocker)
        variant = self._training_variant(mocker)

        _train(mocker, variant)

        dataset_write_calls = [c for c in mock_run.call_args_list if "dataset.json" in c.args[2] and c.args[2].startswith("cat >")]
        assert len(dataset_write_calls) == 1
        written = dataset_write_calls[0].args[2]
        assert "Kumar waving, shot 0" in written
        assert "Kumar waving, shot 9" in written

    def test_blank_caption_falls_back_to_variant_name(self, mocker):
        _, mock_run, _ = self._mock_success(mocker)
        variant = self._training_variant(mocker, captioned=False)

        _train(mocker, variant)

        dataset_write_calls = [c for c in mock_run.call_args_list if "dataset.json" in c.args[2] and c.args[2].startswith("cat >")]
        written = dataset_write_calls[0].args[2]
        assert '"caption": "Kumar"' in written

    def test_uploads_downloaded_bytes_to_the_expected_volume_key(self, mocker):
        _, _, mock_upload = self._mock_success(mocker)
        variant = self._training_variant(mocker)

        _train(mocker, variant)

        mock_upload.assert_called_once_with(b"lora-bytes", f"ComfyUI/models/loras/{_VARIANT_ID}.safetensors")

    def test_downloads_the_located_checkpoint_via_sftp(self, mocker):
        self._mock_success(mocker)
        mock_download = mocker.patch("app.media.runpod_ssh.download_file", return_value=b"lora-bytes")
        variant = self._training_variant(mocker)

        _train(mocker, variant)

        mock_download.assert_called_once_with("1.2.3.4", 2222, _FOUND_CHECKPOINT)

    def test_pod_created_and_terminated_on_success(self, mocker):
        mock_terminate, _, _ = self._mock_success(mocker)
        mock_create = mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", return_value=("1.2.3.4", 2222))
        variant = self._training_variant(mocker)

        _train(mocker, variant)

        mock_create.assert_called_once()
        mock_terminate.assert_called_once_with("pod-123")

    def test_pod_terminated_even_on_failure(self, mocker):
        mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", side_effect=RuntimeError("boom"))
        mock_terminate = mocker.patch("app.media.runpod_client.terminate_pod")
        variant = self._training_variant(mocker)

        with pytest.raises(LoraTrainingError):
            _train(mocker, variant)

        mock_terminate.assert_called_once_with("pod-123")
        assert variant.lora_status == "failed"
        assert "boom" in variant.lora_error

    def test_lora_error_cleared_on_new_attempt(self, mocker):
        # A retry after a prior failure shouldn't leave the old failure
        # message sitting next to a fresh "training" status.
        self._mock_success(mocker)
        variant = self._training_variant(mocker)
        variant.lora_error = "stale error from a previous attempt"

        _train(mocker, variant)

        assert variant.lora_status == "ready"
        assert variant.lora_error is None

    def test_no_pod_created_means_no_termination_attempt(self, mocker):
        # too-few-images case: fails before create_training_pod is ever
        # called, so there's no pod id to terminate.
        mock_terminate = mocker.patch("app.media.runpod_client.terminate_pod")
        variant = _variant(mocker, training_images=_entries(1))
        with pytest.raises(LoraTrainingError):
            _train(mocker, variant)
        mock_terminate.assert_not_called()

    def test_checkpoint_download_failure_sets_failed_status(self, mocker):
        self._mock_success(mocker, fail_on_substring="hf download", fail_result=(1, "", "404 not found"))
        variant = self._training_variant(mocker)

        with pytest.raises(LoraTrainingError, match="404 not found"):
            _train(mocker, variant)

        assert variant.lora_status == "failed"

    def test_image_conversion_failure_sets_failed_status(self, mocker):
        self._mock_success(mocker, fail_on_substring="ffmpeg", fail_result=(1, "", "curl: 404"))
        variant = self._training_variant(mocker)

        with pytest.raises(LoraTrainingError):
            _train(mocker, variant)

        assert variant.lora_status == "failed"

    def test_training_command_failure_sets_failed_status(self, mocker):
        self._mock_success(mocker, fail_on_substring="scripts/train.py", fail_result=(1, "", "CUDA out of memory"))
        variant = self._training_variant(mocker)

        with pytest.raises(LoraTrainingError, match="CUDA out of memory"):
            _train(mocker, variant)

        assert variant.lora_status == "failed"

    def test_missing_output_checkpoint_sets_failed_status(self, mocker):
        mocker.patch("app.media.runpod_client.create_training_pod", return_value="pod-123")
        mocker.patch("app.media.runpod_client.terminate_pod")
        mocker.patch("app.media.runpod_client.wait_for_ssh_ready", return_value=("1.2.3.4", 2222))

        base_fake = _fake_run_remote_command()

        def fake_run(host, port, command, timeout_seconds=1800):
            if command.strip().startswith("ls -1") and "lora_weights_step_" in command:
                return (0, "", "")  # nothing found
            return base_fake(host, port, command, timeout_seconds)
        mocker.patch("app.media.runpod_ssh.run_remote_command", side_effect=fake_run)
        variant = self._training_variant(mocker)

        with pytest.raises(LoraTrainingError, match="Could not find a trained LoRA checkpoint"):
            _train(mocker, variant)

        assert variant.lora_status == "failed"

    def test_s3_upload_failure_sets_failed_status(self, mocker):
        from app.media.runpod_s3 import RunPodS3Error

        self._mock_success(mocker)
        mocker.patch("app.media.runpod_s3.upload_lora", side_effect=RunPodS3Error("connection refused"))
        variant = self._training_variant(mocker)

        with pytest.raises(LoraTrainingError, match="connection refused"):
            _train(mocker, variant)

        assert variant.lora_status == "failed"

    def test_s3_verify_failure_after_upload_sets_failed_status(self, mocker):
        self._mock_success(mocker)
        mocker.patch("app.media.runpod_s3.verify_exists", return_value=False)
        variant = self._training_variant(mocker)

        with pytest.raises(LoraTrainingError, match="Network Volume"):
            _train(mocker, variant)

        assert variant.lora_status == "failed"

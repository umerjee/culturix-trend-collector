"""Tests for app/media/runpod_s3.py — upload/verify against a RunPod
Network Volume's S3-compatible API, mocked at the boto3 client boundary."""
import os

os.environ.setdefault("RUNPOD_S3_ACCESS_KEY_ID", "test-key-id")
os.environ.setdefault("RUNPOD_S3_SECRET_ACCESS_KEY", "test-secret")
os.environ.setdefault("RUNPOD_S3_ENDPOINT_URL", "https://s3api-eu-ro-1.runpod.io")
os.environ.setdefault("RUNPOD_S3_BUCKET", "vol-123")

import pytest

from app.media.runpod_s3 import upload_lora, verify_exists, RunPodS3Error


class TestUploadLora:
    def test_success(self, mocker):
        mock_client = mocker.Mock()
        mocker.patch("boto3.client", return_value=mock_client)

        upload_lora(b"lora-bytes", "ComfyUI/models/loras/variant-1.safetensors")

        mock_client.put_object.assert_called_once_with(
            Bucket="vol-123", Key="ComfyUI/models/loras/variant-1.safetensors", Body=b"lora-bytes",
        )

    def test_put_object_failure_raises_runpods3error(self, mocker):
        mock_client = mocker.Mock()
        mock_client.put_object.side_effect = RuntimeError("connection refused")
        mocker.patch("boto3.client", return_value=mock_client)

        with pytest.raises(RunPodS3Error, match="connection refused"):
            upload_lora(b"lora-bytes", "some/key.safetensors")

    def test_missing_env_var_raises_without_calling_boto3(self, mocker, monkeypatch):
        monkeypatch.delenv("RUNPOD_S3_BUCKET", raising=False)
        mock_boto_client = mocker.patch("boto3.client")
        with pytest.raises(RuntimeError, match="RUNPOD_S3_BUCKET"):
            upload_lora(b"x", "key")
        mock_boto_client.assert_not_called()


class TestVerifyExists:
    def test_returns_true_when_head_object_succeeds(self, mocker):
        mock_client = mocker.Mock()
        mocker.patch("boto3.client", return_value=mock_client)
        assert verify_exists("some/key.safetensors") is True
        mock_client.head_object.assert_called_once_with(Bucket="vol-123", Key="some/key.safetensors")

    def test_returns_false_on_client_error(self, mocker):
        from botocore.exceptions import ClientError

        mock_client = mocker.Mock()
        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject",
        )
        mocker.patch("boto3.client", return_value=mock_client)
        assert verify_exists("missing/key.safetensors") is False

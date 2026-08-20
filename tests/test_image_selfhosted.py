"""Tests for app/media/image_selfhosted.py — RunPod/qwen_image_workflow
mocked at the app.media boundary, no real network."""
import pytest

from app.media.image_selfhosted import SelfHostedImageProvider, SelfHostedImageEditError


class TestSelfHostedImageProviderGenerate:
    def test_requires_reference_image(self):
        with pytest.raises(SelfHostedImageEditError, match="requires reference_image_url"):
            SelfHostedImageProvider().generate("a prompt")

    def test_requires_endpoint_configured(self, monkeypatch):
        monkeypatch.delenv("RUNPOD_IMAGE_SERVERLESS_ENDPOINT_ID", raising=False)
        with pytest.raises(SelfHostedImageEditError, match="RUNPOD_IMAGE_SERVERLESS_ENDPOINT_ID"):
            SelfHostedImageProvider().generate("a prompt", reference_image_url="https://example.com/ref.png")

    def test_success_downloads_reference_builds_workflow_and_returns_result(self, mocker, monkeypatch):
        monkeypatch.setenv("RUNPOD_IMAGE_SERVERLESS_ENDPOINT_ID", "endpoint-1")

        ref_resp = mocker.Mock(content=b"downloaded-ref-bytes")
        ref_resp.raise_for_status = mocker.Mock()
        mocker.patch("httpx.get", return_value=ref_resp)

        mock_build = mocker.patch(
            "app.media.qwen_image_workflow.build_workflow", return_value={"1": {}},
        )
        mock_run = mocker.patch(
            "app.media.runpod_serverless_image_client.run_edit_job_with_allocation_retry",
            return_value=b"final-image-bytes",
        )

        result = SelfHostedImageProvider().generate(
            "make them smile", reference_image_url="https://example.com/portrait.png",
        )

        assert result.asset_bytes == b"final-image-bytes"
        assert result.content_type == "image/png"
        assert result.cost_usd is not None  # placeholder-grade but must not be silently omitted

        mock_build.assert_called_once()
        assert mock_build.call_args.args[0] == "make them smile"

        mock_run.assert_called_once()
        assert mock_run.call_args.args[0] == "endpoint-1"
        assert mock_run.call_args.args[2] == b"downloaded-ref-bytes"

    def test_generation_failure_propagates(self, mocker, monkeypatch):
        monkeypatch.setenv("RUNPOD_IMAGE_SERVERLESS_ENDPOINT_ID", "endpoint-1")
        ref_resp = mocker.Mock(content=b"bytes")
        ref_resp.raise_for_status = mocker.Mock()
        mocker.patch("httpx.get", return_value=ref_resp)
        mocker.patch("app.media.qwen_image_workflow.build_workflow", return_value={"1": {}})
        mocker.patch(
            "app.media.runpod_serverless_image_client.run_edit_job_with_allocation_retry",
            side_effect=RuntimeError("cold start timed out"),
        )

        with pytest.raises(RuntimeError, match="cold start timed out"):
            SelfHostedImageProvider().generate("a prompt", reference_image_url="https://example.com/ref.png")

"""Tests for app/media/runpod_serverless_image_client.py — mocked at the
httpx boundary, RunPod's real API is never touched."""
import base64
import os

os.environ.setdefault("RUNPOD_API_KEY", "test-key")

import pytest

from app.media.runpod_serverless_image_client import (
    run_edit_job, run_edit_job_with_allocation_retry, unique_reference_filename,
    RunPodImageServerlessError,
)


def _mock_response(mocker, json_data, status_code=200):
    resp = mocker.Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = mocker.Mock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


class TestRunEditJob:
    def test_uploads_reference_image_as_base64(self, mocker):
        mock_post = mocker.patch("httpx.post", return_value=_mock_response(mocker, {"id": "job-1"}))
        mocker.patch("httpx.get", return_value=_mock_response(mocker, {
            "status": "COMPLETED",
            "output": {"images": [{"filename": "out.png", "type": "base64", "data": base64.b64encode(b"img-bytes").decode()}]},
        }))
        mocker.patch("time.sleep")

        result = run_edit_job("endpoint-1", {"1": {}}, b"raw-ref-bytes", "ref.png")

        assert result == b"img-bytes"
        sent = mock_post.call_args.kwargs["json"]
        assert sent["input"]["images"] == [{"name": "ref.png", "image": base64.b64encode(b"raw-ref-bytes").decode()}]
        assert sent["input"]["workflow"] == {"1": {}}

    def test_no_job_id_raises(self, mocker):
        mocker.patch("httpx.post", return_value=_mock_response(mocker, {}))
        with pytest.raises(RunPodImageServerlessError, match="no job id"):
            run_edit_job("endpoint-1", {"1": {}}, b"bytes", "ref.png")

    def test_failed_status_raises(self, mocker):
        mocker.patch("httpx.post", return_value=_mock_response(mocker, {"id": "job-1"}))
        mocker.patch("httpx.get", return_value=_mock_response(mocker, {"status": "FAILED", "error": "OOM"}))
        mocker.patch("time.sleep")
        with pytest.raises(RunPodImageServerlessError, match="OOM"):
            run_edit_job("endpoint-1", {"1": {}}, b"bytes", "ref.png")

    def test_output_error_key_raises(self, mocker):
        mocker.patch("httpx.post", return_value=_mock_response(mocker, {"id": "job-1"}))
        mocker.patch("httpx.get", return_value=_mock_response(mocker, {
            "status": "COMPLETED", "output": {"error": "workflow validation failed"},
        }))
        mocker.patch("time.sleep")
        with pytest.raises(RunPodImageServerlessError, match="workflow validation failed"):
            run_edit_job("endpoint-1", {"1": {}}, b"bytes", "ref.png")

    def test_no_images_in_output_raises(self, mocker):
        mocker.patch("httpx.post", return_value=_mock_response(mocker, {"id": "job-1"}))
        mocker.patch("httpx.get", return_value=_mock_response(mocker, {
            "status": "COMPLETED", "output": {"status": "success_no_images", "images": []},
        }))
        mocker.patch("time.sleep")
        with pytest.raises(RunPodImageServerlessError, match="no 'images'"):
            run_edit_job("endpoint-1", {"1": {}}, b"bytes", "ref.png")

    def test_never_completes_raises_timeout(self, mocker):
        mocker.patch("httpx.post", return_value=_mock_response(mocker, {"id": "job-1"}))
        mocker.patch("httpx.get", return_value=_mock_response(mocker, {"status": "IN_QUEUE"}))
        mocker.patch("time.sleep")
        mocker.patch("time.time", side_effect=[0, 0, 100, 200])  # deadline exceeded quickly
        with pytest.raises(TimeoutError):
            run_edit_job("endpoint-1", {"1": {}}, b"bytes", "ref.png", timeout_seconds=1)

    def test_s3_url_output_type_downloads_bytes(self, mocker):
        mocker.patch("httpx.post", return_value=_mock_response(mocker, {"id": "job-1"}))
        status_resp = _mock_response(mocker, {
            "status": "COMPLETED",
            "output": {"images": [{"filename": "out.png", "type": "s3_url", "data": "https://s3/out.png"}]},
        })
        download_resp = mocker.Mock(content=b"downloaded-bytes")
        download_resp.raise_for_status = mocker.Mock()
        mocker.patch("httpx.get", side_effect=[status_resp, download_resp])
        mocker.patch("time.sleep")

        result = run_edit_job("endpoint-1", {"1": {}}, b"bytes", "ref.png")
        assert result == b"downloaded-bytes"


class TestRunEditJobWithAllocationRetry:
    def test_succeeds_immediately_without_sleeping(self, mocker):
        mock_run = mocker.patch(
            "app.media.runpod_serverless_image_client.run_edit_job", return_value=b"img",
        )
        mock_sleep = mocker.patch("time.sleep")
        result = run_edit_job_with_allocation_retry("endpoint-1", {"1": {}}, b"bytes", "ref.png")
        assert result == b"img"
        mock_sleep.assert_not_called()
        mock_run.assert_called_once()

    def test_retries_past_allocation_failure_then_succeeds(self, mocker):
        mocker.patch(
            "app.media.runpod_serverless_image_client.run_edit_job",
            side_effect=[RunPodImageServerlessError("no worker"), b"img"],
        )
        mocker.patch("time.sleep")
        result = run_edit_job_with_allocation_retry(
            "endpoint-1", {"1": {}}, b"bytes", "ref.png", max_retries=1, backoff_seconds=0.01,
        )
        assert result == b"img"

    def test_raises_after_exhausting_retries(self, mocker):
        mocker.patch(
            "app.media.runpod_serverless_image_client.run_edit_job",
            side_effect=RunPodImageServerlessError("still no worker"),
        )
        mocker.patch("time.sleep")
        with pytest.raises(RunPodImageServerlessError, match="failed to allocate a worker after 2 attempt"):
            run_edit_job_with_allocation_retry(
                "endpoint-1", {"1": {}}, b"bytes", "ref.png", max_retries=1, backoff_seconds=0.01,
            )


class TestUniqueReferenceFilename:
    def test_returns_unique_names(self):
        a = unique_reference_filename()
        b = unique_reference_filename()
        assert a != b
        assert a.endswith(".png")

    def test_respects_extension(self):
        assert unique_reference_filename("jpg").endswith(".jpg")

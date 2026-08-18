"""Tests for app/media/runpod_serverless_client.py — submit/poll/output-
extraction against RunPod Serverless's platform-stable job-status contract,
mocked at the httpx boundary. The `input`/`output` payload shape itself is
handler-specific and explicitly unverified (see the module's own header) —
these tests exercise both assumed output shapes the client tries."""
import base64
import os

os.environ.setdefault("RUNPOD_API_KEY", "test-key")

import pytest

from app.media.runpod_serverless_client import (
    run_inference_job, run_inference_job_with_allocation_retry, RunPodServerlessError,
)


def _mock_response(mocker, status_code=200, json_data=None, content=b""):
    resp = mocker.Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.content = content
    resp.raise_for_status = mocker.Mock()
    return resp


class TestRunInferenceJob:
    def test_success_with_base64_output(self, mocker):
        submit_resp = _mock_response(mocker, 200, {"id": "job-1"})
        status_resp = _mock_response(mocker, 200, {
            "status": "COMPLETED", "output": {"video_base64": base64.b64encode(b"video-bytes").decode()},
        })
        mocker.patch("httpx.post", return_value=submit_resp)
        mocker.patch("httpx.get", return_value=status_resp)
        mocker.patch("time.sleep")

        result = run_inference_job("endpoint-1", {"1": {}})
        assert result == b"video-bytes"

    def test_success_with_url_output(self, mocker):
        submit_resp = _mock_response(mocker, 200, {"id": "job-1"})
        status_resp = _mock_response(mocker, 200, {
            "status": "COMPLETED", "output": {"video_url": "https://example.com/out.mp4"},
        })
        video_resp = _mock_response(mocker, 200, content=b"video-from-url")
        mocker.patch("httpx.post", return_value=submit_resp)
        mocker.patch("httpx.get", side_effect=[status_resp, video_resp])
        mocker.patch("time.sleep")

        result = run_inference_job("endpoint-1", {"1": {}})
        assert result == b"video-from-url"

    def test_polls_until_completed(self, mocker):
        submit_resp = _mock_response(mocker, 200, {"id": "job-1"})
        queued_resp = _mock_response(mocker, 200, {"status": "IN_QUEUE"})
        running_resp = _mock_response(mocker, 200, {"status": "IN_PROGRESS"})
        done_resp = _mock_response(mocker, 200, {"status": "COMPLETED", "output": {"video_base64": base64.b64encode(b"x").decode()}})
        mocker.patch("httpx.post", return_value=submit_resp)
        mocker.patch("httpx.get", side_effect=[queued_resp, running_resp, done_resp])
        mocker.patch("time.sleep")

        assert run_inference_job("endpoint-1", {"1": {}}) == b"x"

    def test_missing_job_id_raises(self, mocker):
        submit_resp = _mock_response(mocker, 200, {"no_id_here": True})
        mocker.patch("httpx.post", return_value=submit_resp)
        with pytest.raises(RunPodServerlessError):
            run_inference_job("endpoint-1", {"1": {}})

    def test_failed_status_raises(self, mocker):
        submit_resp = _mock_response(mocker, 200, {"id": "job-1"})
        status_resp = _mock_response(mocker, 200, {"status": "FAILED", "error": "OOM"})
        mocker.patch("httpx.post", return_value=submit_resp)
        mocker.patch("httpx.get", return_value=status_resp)
        mocker.patch("time.sleep")

        with pytest.raises(RunPodServerlessError, match="OOM"):
            run_inference_job("endpoint-1", {"1": {}})

    def test_unrecognized_output_shape_raises(self, mocker):
        submit_resp = _mock_response(mocker, 200, {"id": "job-1"})
        status_resp = _mock_response(mocker, 200, {"status": "COMPLETED", "output": {"something_else": 1}})
        mocker.patch("httpx.post", return_value=submit_resp)
        mocker.patch("httpx.get", return_value=status_resp)
        mocker.patch("time.sleep")

        with pytest.raises(RunPodServerlessError, match="video_base64"):
            run_inference_job("endpoint-1", {"1": {}})

    def test_timeout_raises(self, mocker):
        submit_resp = _mock_response(mocker, 200, {"id": "job-1"})
        queued_resp = _mock_response(mocker, 200, {"status": "IN_QUEUE"})
        mocker.patch("httpx.post", return_value=submit_resp)
        mocker.patch("httpx.get", return_value=queued_resp)
        mocker.patch("time.sleep")
        fake_time = mocker.patch("time.time")
        fake_time.side_effect = [0, 0, 1000]

        with pytest.raises(TimeoutError):
            run_inference_job("endpoint-1", {"1": {}}, timeout_seconds=30)

    def test_missing_api_key_raises(self, mocker, monkeypatch):
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
        with pytest.raises(RuntimeError):
            run_inference_job("endpoint-1", {"1": {}})


class TestRunInferenceJobWithAllocationRetry:
    def test_succeeds_on_first_try_without_retrying(self, mocker):
        mock_job = mocker.patch(
            "app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes",
        )
        mock_sleep = mocker.patch("time.sleep")

        result = run_inference_job_with_allocation_retry("endpoint-1", {"1": {}}, max_retries=1, backoff_seconds=1)

        assert result == b"video-bytes"
        mock_job.assert_called_once()
        mock_sleep.assert_not_called()

    def test_retries_once_after_allocation_failure_then_succeeds(self, mocker):
        mock_job = mocker.patch(
            "app.media.runpod_serverless_client.run_inference_job",
            side_effect=[TimeoutError("no worker available"), b"video-bytes"],
        )
        mock_sleep = mocker.patch("time.sleep")

        result = run_inference_job_with_allocation_retry("endpoint-1", {"1": {}}, max_retries=1, backoff_seconds=45)

        assert result == b"video-bytes"
        assert mock_job.call_count == 2
        mock_sleep.assert_called_once_with(45)

    def test_raises_after_exhausting_retries(self, mocker):
        mocker.patch(
            "app.media.runpod_serverless_client.run_inference_job",
            side_effect=RunPodServerlessError("no capacity"),
        )
        mocker.patch("time.sleep")

        with pytest.raises(RunPodServerlessError, match="no capacity"):
            run_inference_job_with_allocation_retry("endpoint-1", {"1": {}}, max_retries=1, backoff_seconds=1)

    def test_reads_retry_config_from_env_when_not_passed(self, mocker, monkeypatch):
        monkeypatch.setenv("RUNPOD_ALLOCATION_MAX_RETRIES", "2")
        monkeypatch.setenv("RUNPOD_ALLOCATION_BACKOFF_SECONDS", "5")
        mock_job = mocker.patch(
            "app.media.runpod_serverless_client.run_inference_job",
            side_effect=[TimeoutError("x"), TimeoutError("x"), b"video-bytes"],
        )
        mock_sleep = mocker.patch("time.sleep")

        result = run_inference_job_with_allocation_retry("endpoint-1", {"1": {}})

        assert result == b"video-bytes"
        assert mock_job.call_count == 3
        mock_sleep.assert_called_with(5.0)

"""Tests for app/media/runpod_serverless_client.py — submit/poll/output-
extraction against RunPod Serverless's platform-stable job-status contract,
mocked at the httpx boundary. The `input`/`output` payload shape itself is
handler-specific and explicitly unverified (see the module's own header) —
these tests exercise both assumed output shapes the client tries."""
import base64
import os

os.environ.setdefault("RUNPOD_API_KEY", "test-key")

import pytest

from app.media.runpod_serverless_client import run_inference_job, RunPodServerlessError


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

"""Tests for app/media/runpod_serverless_client.py — submit/poll/output-
extraction against RunPod Serverless's platform-stable job-status contract,
mocked at the httpx boundary. The `input`/`output` payload shape itself is
handler-specific and explicitly unverified (see the module's own header) —
these tests exercise both assumed output shapes the client tries."""
import base64
import os
from unittest.mock import MagicMock

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
        # [0, 0] establishes the deadline and passes the first while-check (poll once,
        # "IN_QUEUE"); every call after that returns 1000, comfortably past the 30s
        # deadline, so the loop exits on its next check. A side_effect sized to the
        # *exact* minimum expected call count (the original [0, 0, 1000]) is fragile —
        # confirmed live in CI (github.com Actions run, ubuntu/Python 3.11, this exact
        # test): it raised StopIteration instead of TimeoutError, meaning something in
        # that environment made one more time.time() call than this local run does.
        # Not reproducible locally in isolation or as part of the full suite (Windows/
        # Python 3.14) despite direct instrumentation of the real call path, so this
        # pads generously rather than chasing an exact count this test does not
        # actually care about — the assertion is "did it time out correctly," not
        # "exactly how many times was time.time() called."
        mocker.patch("time.time", side_effect=[0, 0] + [1000] * 20)

        with pytest.raises(TimeoutError):
            run_inference_job("endpoint-1", {"1": {}}, timeout_seconds=30)

    def test_timeout_exception_carries_job_id(self, mocker):
        """The job_id lets a caller identify/log which specific job timed
        out (RunPod's own queue keeps it running server-side regardless of
        what this client does)."""
        submit_resp = _mock_response(mocker, 200, {"id": "job-orphan-1"})
        queued_resp = _mock_response(mocker, 200, {"status": "IN_QUEUE"})
        mocker.patch("httpx.post", return_value=submit_resp)
        mocker.patch("httpx.get", return_value=queued_resp)
        mocker.patch("time.sleep")
        mocker.patch("time.time", side_effect=[0, 0] + [1000] * 20)  # see test_timeout_raises

        with pytest.raises(TimeoutError) as exc_info:
            run_inference_job("endpoint-1", {"1": {}}, timeout_seconds=30)
        assert exc_info.value.job_id == "job-orphan-1"

    def test_failed_exception_carries_job_id(self, mocker):
        submit_resp = _mock_response(mocker, 200, {"id": "job-failed-1"})
        status_resp = _mock_response(mocker, 200, {"status": "FAILED", "error": "OOM"})
        mocker.patch("httpx.post", return_value=submit_resp)
        mocker.patch("httpx.get", return_value=status_resp)
        mocker.patch("time.sleep")

        with pytest.raises(RunPodServerlessError) as exc_info:
            run_inference_job("endpoint-1", {"1": {}})
        assert exc_info.value.job_id == "job-failed-1"

    def test_missing_api_key_raises(self, mocker, monkeypatch):
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
        with pytest.raises(RuntimeError):
            run_inference_job("endpoint-1", {"1": {}})


class TestCancelsAbandonedJobs:
    """A job we stop waiting for keeps running on the GPU and keeps billing, so it must be cancelled."""

    @staticmethod
    def _posted_urls(post):
        return [call.args[0] for call in post.call_args_list]

    def test_timeout_cancels_the_job(self, mocker):
        post = mocker.patch("httpx.post", return_value=MagicMock(json=lambda: {"id": "job-9"}))
        mocker.patch("httpx.get", return_value=MagicMock(json=lambda: {"status": "IN_PROGRESS"}))
        mocker.patch("time.sleep")
        fake_time = mocker.patch("time.time")
        fake_time.side_effect = [0, 0, 100, 100, 100]
        with pytest.raises(TimeoutError):
            run_inference_job("ep-1", {"wf": 1}, timeout_seconds=50)
        assert any(url.endswith("/ep-1/cancel/job-9") for url in self._posted_urls(post))

    def test_a_network_error_while_polling_cancels_the_job(self, mocker):
        post = mocker.patch("httpx.post", return_value=MagicMock(json=lambda: {"id": "job-9"}))
        mocker.patch("httpx.get", side_effect=RuntimeError("connection reset"))
        mocker.patch("time.sleep")
        with pytest.raises(RuntimeError):
            run_inference_job("ep-1", {"wf": 1})
        assert any(url.endswith("/ep-1/cancel/job-9") for url in self._posted_urls(post))

    @pytest.mark.parametrize("status", ["COMPLETED", "FAILED"])
    def test_a_finished_job_is_not_cancelled(self, mocker, status):
        post = mocker.patch("httpx.post", return_value=MagicMock(json=lambda: {"id": "job-9"}))
        mocker.patch("httpx.get", return_value=MagicMock(json=lambda: {"status": status, "output": {"video_base64": "AAAA"}}))
        mocker.patch("time.sleep")
        try:
            run_inference_job("ep-1", {"wf": 1})
        except RunPodServerlessError:
            pass
        assert not any("/cancel/" in url for url in self._posted_urls(post))

    @pytest.mark.parametrize("status", ["CANCELLED", "TIMED_OUT"])
    def test_a_job_ended_by_runpod_fails_at_once_instead_of_polling_to_the_timeout(self, mocker, status):
        post = mocker.patch("httpx.post", return_value=MagicMock(json=lambda: {"id": "job-9"}))
        get = mocker.patch("httpx.get", return_value=MagicMock(json=lambda: {"status": status}))
        mocker.patch("time.sleep")
        with pytest.raises(RunPodServerlessError) as excinfo:
            run_inference_job("ep-1", {"wf": 1})
        assert status in str(excinfo.value) and excinfo.value.job_id == "job-9"
        assert get.call_count == 1
        assert not any("/cancel/" in url for url in self._posted_urls(post))

    def test_a_failed_cancel_never_masks_the_real_error(self, mocker):
        def post(url, **kw):
            if "/cancel/" in url:
                raise RuntimeError("runpod down")
            return MagicMock(json=lambda: {"id": "job-9"})
        mocker.patch("httpx.post", side_effect=post)
        mocker.patch("httpx.get", side_effect=ValueError("poll broke"))
        mocker.patch("time.sleep")
        with pytest.raises(ValueError, match="poll broke"):
            run_inference_job("ep-1", {"wf": 1})

    def test_shutdown_cancels_jobs_still_being_waited_on(self, mocker):
        from app.media import runpod_serverless_client as client
        post = mocker.patch("httpx.post", return_value=MagicMock())
        client._active_jobs.clear()
        client._active_jobs.update({"job-a": "ep-1", "job-b": "ep-2"})
        assert client.cancel_all_active_jobs() == 2
        assert sorted(self._posted_urls(post)) == sorted([
            "https://api.runpod.ai/v2/ep-1/cancel/job-a", "https://api.runpod.ai/v2/ep-2/cancel/job-b"])
        assert client._active_jobs == {}


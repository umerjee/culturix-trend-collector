"""Tests for app/media/comfyui_client.py's submit/poll/download logic —
mocked at the httpx boundary, same convention as tests/test_kling* etc."""
import pytest

from app.media.comfyui_client import submit_workflow, wait_for_completion, download_output, ComfyUIError


def _mock_response(mocker, status_code=200, json_data=None, content=b"", text=""):
    resp = mocker.Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.content = content
    resp.text = text
    resp.raise_for_status = mocker.Mock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=mocker.Mock(), response=resp)
    return resp


class TestSubmitWorkflow:
    def test_returns_prompt_id_on_success(self, mocker):
        resp = _mock_response(mocker, 200, {"prompt_id": "abc123"})
        mocker.patch("httpx.post", return_value=resp)
        assert submit_workflow("http://host:8188", {"1": {}}) == "abc123"

    def test_non_200_raises_comfyui_error(self, mocker):
        resp = _mock_response(mocker, 400, {}, text="bad node")
        mocker.patch("httpx.post", return_value=resp)
        with pytest.raises(ComfyUIError):
            submit_workflow("http://host:8188", {"1": {}})

    def test_missing_prompt_id_raises(self, mocker):
        resp = _mock_response(mocker, 200, {"something_else": True})
        mocker.patch("httpx.post", return_value=resp)
        with pytest.raises(ComfyUIError):
            submit_workflow("http://host:8188", {"1": {}})


class TestWaitForCompletion:
    def test_returns_entry_once_present(self, mocker):
        resp = _mock_response(mocker, 200, {"abc123": {"status": {"completed": True}, "outputs": {}}})
        mocker.patch("httpx.get", return_value=resp)
        mocker.patch("time.sleep")
        entry = wait_for_completion("http://host:8188", "abc123", timeout_seconds=30)
        assert entry == {"status": {"completed": True}, "outputs": {}}

    def test_polls_until_entry_appears(self, mocker):
        empty_resp = _mock_response(mocker, 200, {})
        ready_resp = _mock_response(mocker, 200, {"abc123": {"status": {"completed": True}, "outputs": {}}})
        mocker.patch("httpx.get", side_effect=[empty_resp, empty_resp, ready_resp])
        mocker.patch("time.sleep")
        entry = wait_for_completion("http://host:8188", "abc123", timeout_seconds=30)
        assert entry["outputs"] == {}

    def test_error_status_raises_comfyui_error(self, mocker):
        resp = _mock_response(mocker, 200, {"abc123": {"status": {"status_str": "error", "messages": ["boom"]}}})
        mocker.patch("httpx.get", return_value=resp)
        mocker.patch("time.sleep")
        with pytest.raises(ComfyUIError):
            wait_for_completion("http://host:8188", "abc123", timeout_seconds=30)

    def test_timeout_raises(self, mocker):
        resp = _mock_response(mocker, 200, {})
        mocker.patch("httpx.get", return_value=resp)
        fake_time = mocker.patch("time.time")
        fake_time.side_effect = [0, 0, 1000]  # deadline computed at 0+30, then immediately past it
        mocker.patch("time.sleep")
        with pytest.raises(TimeoutError):
            wait_for_completion("http://host:8188", "abc123", timeout_seconds=30)


class TestDownloadOutput:
    def test_downloads_first_video_output(self, mocker):
        history_entry = {"outputs": {"8": {"videos": [{"filename": "out.mp4", "subfolder": "", "type": "output"}]}}}
        resp = _mock_response(mocker, 200, content=b"video-bytes")
        mocker.patch("httpx.get", return_value=resp)
        assert download_output("http://host:8188", history_entry) == b"video-bytes"

    def test_falls_back_to_gifs_key(self, mocker):
        history_entry = {"outputs": {"8": {"gifs": [{"filename": "out.webp", "type": "output"}]}}}
        resp = _mock_response(mocker, 200, content=b"gif-bytes")
        mocker.patch("httpx.get", return_value=resp)
        assert download_output("http://host:8188", history_entry) == b"gif-bytes"

    def test_no_output_raises(self, mocker):
        with pytest.raises(ComfyUIError):
            download_output("http://host:8188", {"outputs": {"8": {}}})

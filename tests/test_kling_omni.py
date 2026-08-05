"""Tests for app/media/kling_omni.py — the new Kling 3.0 Omni provider.
Mocks httpx.request/httpx.get entirely (no real network calls), matching
this codebase's established test doctrine. time.sleep is mocked so polling
loops run instantly regardless of the real poll-interval constants.
"""
import os
os.environ.setdefault("KLING_ACCESS_KEY", "test-access-key")
os.environ.setdefault("KLING_SECRET_KEY", "test-secret-key")

import pytest

from app.media.kling_omni import KlingOmniProvider, KlingOmniError


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, content=b""):
        self._json = json_data or {}
        self.status_code = status_code
        self.content = content
        self.headers = {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def _no_real_sleep(mocker):
    mocker.patch("time.sleep")


class TestCreateElement:
    def test_success(self, mocker):
        create_resp = _FakeResponse({"code": 0, "data": {"task_id": "t1", "task_status": "submitted"}})
        poll_resp = _FakeResponse({
            "code": 0,
            "data": {"task_status": "succeed", "task_result": {"elements": [{"element_id": "e1"}]}},
        })
        mocker.patch("httpx.request", return_value=create_resp)
        mocker.patch("httpx.get", return_value=poll_resp)

        element_id = KlingOmniProvider().create_element(
            "Indian Mom", "A warm but exasperated mother", "https://img/frontal.png",
        )
        assert element_id == "e1"

    def test_task_failed(self, mocker):
        create_resp = _FakeResponse({"code": 0, "data": {"task_id": "t1"}})
        poll_resp = _FakeResponse({"code": 0, "data": {"task_status": "failed", "task_status_msg": "bad image"}})
        mocker.patch("httpx.request", return_value=create_resp)
        mocker.patch("httpx.get", return_value=poll_resp)

        with pytest.raises(KlingOmniError, match="bad image"):
            KlingOmniProvider().create_element("Mom", "desc", "https://img/f.png")

    def test_poll_timeout(self, mocker):
        create_resp = _FakeResponse({"code": 0, "data": {"task_id": "t1"}})
        poll_resp = _FakeResponse({"code": 0, "data": {"task_status": "processing"}})
        mocker.patch("httpx.request", return_value=create_resp)
        mocker.patch("httpx.get", return_value=poll_resp)
        mocker.patch("app.media.kling_omni._ELEMENT_MAX_POLLS", 2)

        with pytest.raises(KlingOmniError, match="did not complete in time"):
            KlingOmniProvider().create_element("Mom", "desc", "https://img/f.png")


class TestCreateVoice:
    def test_success(self, mocker):
        create_resp = _FakeResponse({"code": 0, "data": {"task_id": "t2"}})
        poll_resp = _FakeResponse({
            "code": 0, "data": {"task_status": "succeed", "task_result": {"voices": [{"voice_id": "v1"}]}},
        })
        mocker.patch("httpx.request", return_value=create_resp)
        mocker.patch("httpx.get", return_value=poll_resp)

        voice_id = KlingOmniProvider().create_voice("Mom Voice", "https://audio/sample.mp3")
        assert voice_id == "v1"


class TestGenerateOmniVideo:
    def test_success(self, mocker):
        create_resp = _FakeResponse({"code": 0, "data": {"id": "task1", "status": "submitted"}})
        poll_resp = _FakeResponse({
            "code": 0,
            "data": [{"status": "succeeded", "outputs": [
                {"type": "video", "url": "https://cdn/video.mp4", "duration": "8"},
            ]}],
        })
        video_resp = _FakeResponse(content=b"fake-video-bytes")

        mocker.patch("httpx.request", return_value=create_resp)
        mocker.patch("httpx.get", side_effect=[poll_resp, video_resp])

        result = KlingOmniProvider().generate_omni_video(
            contents=[{"type": "prompt", "text": "shot 1, 5, @Mom waves;"}],
            settings={"multi_shot": True, "duration": 8},
        )
        assert result["video_bytes"] == b"fake-video-bytes"
        assert result["duration_seconds"] == 8.0
        assert result["task_id"] == "task1"

    def test_task_failed(self, mocker):
        create_resp = _FakeResponse({"code": 0, "data": {"id": "task1"}})
        poll_resp = _FakeResponse({"code": 0, "data": [{"status": "failed", "message": "content risk control"}]})
        mocker.patch("httpx.request", return_value=create_resp)
        mocker.patch("httpx.get", return_value=poll_resp)

        with pytest.raises(KlingOmniError, match="content risk control"):
            KlingOmniProvider().generate_omni_video(contents=[], settings={})

    def test_poll_timeout(self, mocker):
        create_resp = _FakeResponse({"code": 0, "data": {"id": "task1"}})
        poll_resp = _FakeResponse({"code": 0, "data": [{"status": "processing"}]})
        mocker.patch("httpx.request", return_value=create_resp)
        mocker.patch("httpx.get", return_value=poll_resp)
        mocker.patch("app.media.kling_omni._OMNI_MAX_POLLS", 2)

        with pytest.raises(KlingOmniError, match="did not complete in time"):
            KlingOmniProvider().generate_omni_video(contents=[], settings={})


class TestMissingCredentials:
    def test_raises_without_access_key(self, mocker):
        mocker.patch.dict(os.environ, {"KLING_ACCESS_KEY": ""})
        with pytest.raises(RuntimeError, match="KLING_ACCESS_KEY"):
            KlingOmniProvider()

    def test_raises_without_secret_key(self, mocker):
        mocker.patch.dict(os.environ, {"KLING_SECRET_KEY": ""})
        with pytest.raises(RuntimeError, match="KLING_ACCESS_KEY"):
            KlingOmniProvider()

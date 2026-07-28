from unittest.mock import Mock

from app.media.video import KlingProvider


def _create_resp(task_id="task-123"):
    resp = Mock(status_code=200)
    resp.json.return_value = {"data": {"task_id": task_id}}
    resp.raise_for_status = Mock()
    return resp


def _poll_resp(status="succeed", video_url="https://cdn.klingai.com/out.mp4", msg=None):
    resp = Mock(status_code=200)
    body = {"data": {"task_status": status}}
    if status == "succeed":
        body["data"]["task_result"] = {"videos": [{"url": video_url}]}
    if status == "failed":
        body["data"]["task_status_msg"] = msg or "generation failed"
    resp.json.return_value = body
    resp.raise_for_status = Mock()
    return resp


def _video_bytes_resp():
    resp = Mock(status_code=200)
    resp.content = b"fake-mp4-bytes"
    resp.raise_for_status = Mock()
    return resp


class TestKlingProviderTextToVideo:
    def test_creates_text2video_task_when_no_reference_image(self, mocker, monkeypatch):
        monkeypatch.setenv("KLING_ACCESS_KEY", "ak")
        monkeypatch.setenv("KLING_SECRET_KEY", "sk")
        mocker.patch("app.media.video._make_jwt", return_value="fake-jwt")
        mock_post = mocker.patch("app.media.video._post_with_retry", return_value=_create_resp())
        mocker.patch("app.media.video.httpx.get", side_effect=[_poll_resp(), _video_bytes_resp()])
        mocker.patch("app.media.video.time.sleep")

        result = KlingProvider().generate("A dramatic photo of a baseball player")

        sent_url = mock_post.call_args.args[0]
        sent_body = mock_post.call_args.kwargs["json"]
        assert sent_url.endswith("/v1/videos/text2video")
        assert sent_body["prompt"] == "A dramatic photo of a baseball player"
        assert sent_body["aspect_ratio"] == "9:16"
        assert "image" not in sent_body
        assert result.asset_bytes == b"fake-mp4-bytes"
        assert result.content_type == "video/mp4"


class TestKlingProviderImageToVideo:
    def test_creates_image2video_task_when_reference_image_provided(self, mocker, monkeypatch):
        monkeypatch.setenv("KLING_ACCESS_KEY", "ak")
        monkeypatch.setenv("KLING_SECRET_KEY", "sk")
        mocker.patch("app.media.video._make_jwt", return_value="fake-jwt")
        mock_post = mocker.patch("app.media.video._post_with_retry", return_value=_create_resp())
        mocker.patch("app.media.video.httpx.get", side_effect=[_poll_resp(), _video_bytes_resp()])
        mocker.patch("app.media.video.time.sleep")

        reference_url = "https://cdn.shopify.com/products/kurta.jpg"
        result = KlingProvider().generate(
            "Fabric gently moves in a soft breeze, cinematic lighting",
            reference_image_url=reference_url,
        )

        sent_url = mock_post.call_args.args[0]
        sent_body = mock_post.call_args.kwargs["json"]
        assert sent_url.endswith("/v1/videos/image2video")
        assert sent_body["image"] == reference_url
        assert "aspect_ratio" not in sent_body
        assert result.asset_bytes == b"fake-mp4-bytes"

    def test_polls_image2video_status_endpoint_not_text2video(self, mocker, monkeypatch):
        monkeypatch.setenv("KLING_ACCESS_KEY", "ak")
        monkeypatch.setenv("KLING_SECRET_KEY", "sk")
        mocker.patch("app.media.video._make_jwt", return_value="fake-jwt")
        mocker.patch("app.media.video._post_with_retry", return_value=_create_resp())
        mock_get = mocker.patch("app.media.video.httpx.get", side_effect=[_poll_resp(), _video_bytes_resp()])
        mocker.patch("app.media.video.time.sleep")

        KlingProvider().generate("prompt", reference_image_url="https://cdn.shopify.com/x.jpg")

        poll_call_url = mock_get.call_args_list[0].args[0]
        assert "/v1/videos/image2video/task-123" in poll_call_url

    def test_raises_on_failed_task(self, mocker, monkeypatch):
        monkeypatch.setenv("KLING_ACCESS_KEY", "ak")
        monkeypatch.setenv("KLING_SECRET_KEY", "sk")
        mocker.patch("app.media.video._make_jwt", return_value="fake-jwt")
        mocker.patch("app.media.video._post_with_retry", return_value=_create_resp())
        mocker.patch("app.media.video.httpx.get", return_value=_poll_resp(status="failed", msg="unsafe image"))
        mocker.patch("app.media.video.time.sleep")

        try:
            KlingProvider().generate("prompt", reference_image_url="https://cdn.shopify.com/x.jpg")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "unsafe image" in str(e)


class TestKlingProviderInit:
    def test_raises_if_no_credentials(self, monkeypatch):
        monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
        monkeypatch.delenv("KLING_SECRET_KEY", raising=False)
        try:
            KlingProvider()
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "KLING_ACCESS_KEY" in str(e)

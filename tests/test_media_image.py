from unittest.mock import Mock

from app.media.image import QwenImageProvider


def _fake_generation_response(image_url="https://dashscope-intl.example.com/gen-abc.png"):
    resp = Mock(status_code=200)
    resp.json.return_value = {
        "output": {"choices": [{"message": {"content": [{"image": image_url}]}}]}
    }
    resp.raise_for_status = Mock()
    return resp


def _fake_image_bytes_response():
    resp = Mock(status_code=200)
    resp.content = b"fake-png-bytes"
    resp.raise_for_status = Mock()
    return resp


class TestQwenImageProviderGenerate:
    def test_text_only_when_no_reference_image(self, mocker, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "test-key")
        mock_post = mocker.patch("app.media.image.httpx.post", return_value=_fake_generation_response())
        mocker.patch("app.media.image.httpx.get", return_value=_fake_image_bytes_response())

        result = QwenImageProvider().generate("A dramatic photo of a baseball player")

        sent_body = mock_post.call_args.kwargs["json"]
        content = sent_body["input"]["messages"][0]["content"]
        assert content == [{"text": "A dramatic photo of a baseball player"}]
        assert result.asset_bytes == b"fake-png-bytes"

    def test_includes_reference_image_when_provided(self, mocker, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "test-key")
        mock_post = mocker.patch("app.media.image.httpx.post", return_value=_fake_generation_response())
        mocker.patch("app.media.image.httpx.get", return_value=_fake_image_bytes_response())

        reference_url = "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
        QwenImageProvider().generate("A dramatic photo of Trea Turner", reference_image_url=reference_url)

        sent_body = mock_post.call_args.kwargs["json"]
        content = sent_body["input"]["messages"][0]["content"]
        assert content[0] == {"image": reference_url}
        assert content[1] == {"text": "A dramatic photo of Trea Turner"}

    def test_raises_if_no_api_key(self, monkeypatch):
        monkeypatch.delenv("QWEN_API_KEY", raising=False)
        try:
            QwenImageProvider().generate("prompt")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "QWEN_API_KEY" in str(e)

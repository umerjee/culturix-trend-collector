import base64
from unittest.mock import Mock

from app.media.image_cloudflare import CloudflareFluxProvider


def _fake_response(image_b64="ZmFrZS1qcGVnLWJ5dGVz", wrapped=True):
    resp = Mock(status_code=200)
    body = {"success": True, "result": {"image": image_b64}} if wrapped else {"image": image_b64}
    resp.json.return_value = body
    resp.raise_for_status = Mock()
    return resp


class TestCloudflareFluxProviderGenerate:
    def test_decodes_base64_image_from_wrapped_result(self, mocker, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")
        mock_post = mocker.patch("app.media.image_cloudflare.httpx.post", return_value=_fake_response())

        result = CloudflareFluxProvider().generate("A dramatic photo of a baseball player")

        assert result.asset_bytes == base64.b64decode("ZmFrZS1qcGVnLWJ5dGVz")
        assert result.content_type == "image/jpeg"
        assert result.cost_usd == 0.0
        sent = mock_post.call_args
        assert "flux-1-schnell" in sent.args[0]
        assert sent.kwargs["headers"]["Authorization"] == "Bearer token-abc"

    def test_decodes_base64_image_from_bare_shape(self, mocker, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")
        mocker.patch(
            "app.media.image_cloudflare.httpx.post",
            return_value=_fake_response(wrapped=False),
        )

        result = CloudflareFluxProvider().generate("prompt")
        assert result.asset_bytes == base64.b64decode("ZmFrZS1qcGVnLWJ5dGVz")

    def test_raises_on_api_error(self, mocker, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")
        resp = Mock(status_code=200)
        resp.json.return_value = {"success": False, "errors": [{"message": "rate limited"}]}
        resp.raise_for_status = Mock()
        mocker.patch("app.media.image_cloudflare.httpx.post", return_value=resp)

        try:
            CloudflareFluxProvider().generate("prompt")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "rate limited" in str(e)

    def test_raises_if_no_credentials(self, monkeypatch):
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        try:
            CloudflareFluxProvider().generate("prompt")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "CLOUDFLARE_ACCOUNT_ID" in str(e)

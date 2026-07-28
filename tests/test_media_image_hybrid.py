from app.media.base import MediaResult
from app.media.image_hybrid import HybridImageProvider


class TestHybridImageProviderGenerate:
    def test_uses_cloudflare_when_no_reference_image(self, mocker):
        cf_result = MediaResult(asset_bytes=b"cf", content_type="image/jpeg")
        mock_cf = mocker.patch("app.media.image_cloudflare.CloudflareFluxProvider")
        mock_cf.return_value.generate.return_value = cf_result
        mock_qwen = mocker.patch("app.media.image.QwenImageProvider")

        result = HybridImageProvider().generate("a prompt")

        assert result is cf_result
        mock_qwen.return_value.generate.assert_not_called()

    def test_falls_back_to_qwen_when_cloudflare_fails(self, mocker):
        mock_cf = mocker.patch("app.media.image_cloudflare.CloudflareFluxProvider")
        mock_cf.return_value.generate.side_effect = RuntimeError("no credentials")
        qwen_result = MediaResult(asset_bytes=b"qwen", content_type="image/png")
        mock_qwen = mocker.patch("app.media.image.QwenImageProvider")
        mock_qwen.return_value.generate.return_value = qwen_result

        result = HybridImageProvider().generate("a prompt")

        assert result is qwen_result

    def test_skips_cloudflare_straight_to_qwen_when_reference_image_given(self, mocker):
        mock_cf = mocker.patch("app.media.image_cloudflare.CloudflareFluxProvider")
        qwen_result = MediaResult(asset_bytes=b"qwen", content_type="image/png")
        mock_qwen = mocker.patch("app.media.image.QwenImageProvider")
        mock_qwen.return_value.generate.return_value = qwen_result

        result = HybridImageProvider().generate("a prompt", reference_image_url="https://example.com/ref.jpg")

        assert result is qwen_result
        mock_cf.assert_not_called()
        mock_qwen.return_value.generate.assert_called_once_with(
            "a prompt", reference_image_url="https://example.com/ref.jpg"
        )

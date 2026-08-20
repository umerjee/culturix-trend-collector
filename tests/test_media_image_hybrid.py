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

    def test_skips_cloudflare_straight_to_self_hosted_when_reference_image_given(self, mocker):
        # Confirmed live 2026-08-20: every Expression generation (always
        # reference-grounded) was falling straight to paid Qwen-Image
        # before this tier existed — this is the fix for that.
        mock_cf = mocker.patch("app.media.image_cloudflare.CloudflareFluxProvider")
        selfhosted_result = MediaResult(asset_bytes=b"selfhosted", content_type="image/png")
        mock_selfhosted = mocker.patch("app.media.image_selfhosted.SelfHostedImageProvider")
        mock_selfhosted.return_value.generate.return_value = selfhosted_result
        mock_qwen = mocker.patch("app.media.image.QwenImageProvider")

        result = HybridImageProvider().generate("a prompt", reference_image_url="https://example.com/ref.jpg")

        assert result is selfhosted_result
        mock_cf.assert_not_called()
        mock_qwen.return_value.generate.assert_not_called()
        mock_selfhosted.return_value.generate.assert_called_once_with(
            "a prompt", reference_image_url="https://example.com/ref.jpg"
        )

    def test_falls_back_to_qwen_when_self_hosted_fails(self, mocker):
        mock_selfhosted = mocker.patch("app.media.image_selfhosted.SelfHostedImageProvider")
        mock_selfhosted.return_value.generate.side_effect = RuntimeError("RUNPOD_IMAGE_SERVERLESS_ENDPOINT_ID is not configured")
        qwen_result = MediaResult(asset_bytes=b"qwen", content_type="image/png")
        mock_qwen = mocker.patch("app.media.image.QwenImageProvider")
        mock_qwen.return_value.generate.return_value = qwen_result

        result = HybridImageProvider().generate("a prompt", reference_image_url="https://example.com/ref.jpg")

        assert result is qwen_result
        mock_qwen.return_value.generate.assert_called_once_with(
            "a prompt", reference_image_url="https://example.com/ref.jpg"
        )

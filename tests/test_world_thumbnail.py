from app.media.base import MediaResult
from app.services.world_thumbnail import build_world_thumbnail_prompt, generate_world_thumbnail


class TestBuildWorldThumbnailPrompt:
    def test_includes_the_subject_and_the_fixed_style(self):
        prompt = build_world_thumbnail_prompt("Mimic Octopus' Unique Mimicry Abilities")
        assert "Mimic Octopus' Unique Mimicry Abilities" in prompt
        assert "editorial illustration" in prompt
        assert "portrait orientation" in prompt

    def test_two_different_subjects_share_the_exact_same_style_text(self):
        # The whole point is consistency: every thumbnail must carry the identical style
        # directive, only the subject line differs.
        a = build_world_thumbnail_prompt("Axolotl")
        b = build_world_thumbnail_prompt("CRISPR-Cas9 Gene Editing")
        style_a = a.split(". ", 1)[1]
        style_b = b.split(". ", 1)[1]
        assert style_a == style_b


class TestGenerateWorldThumbnail:
    def test_a_successful_generation_uploads_and_returns_the_url(self, mocker):
        mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png-bytes", content_type="image/png", cost_usd=0.0),
        )
        upload = mocker.patch("app.media.storage.upload", return_value="https://cdn/world-thumbnails/abc.png")

        url = generate_world_thumbnail("abc", "Axolotl's Unique Regeneration Abilities")

        assert url == "https://cdn/world-thumbnails/abc.png"
        upload.assert_called_once()
        args, kwargs = upload.call_args
        assert args[0] == b"fake-png-bytes"
        assert args[1] == "world-thumbnails/abc.png"
        assert args[2] == "image/png"

    def test_a_jpeg_result_gets_a_jpg_extension(self, mocker):
        mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"x", content_type="image/jpeg", cost_usd=0.0),
        )
        upload = mocker.patch("app.media.storage.upload", return_value="https://cdn/x.jpg")

        generate_world_thumbnail("abc", "Some subject")

        assert upload.call_args.args[1] == "world-thumbnails/abc.jpg"

    def test_a_provider_failure_returns_none_not_an_exception(self, mocker):
        mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            side_effect=RuntimeError("provider down"),
        )
        assert generate_world_thumbnail("abc", "Some subject") is None

    def test_an_upload_failure_returns_none_not_an_exception(self, mocker):
        mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"x", content_type="image/png", cost_usd=0.0),
        )
        mocker.patch("app.media.storage.upload", side_effect=RuntimeError("storage down"))
        assert generate_world_thumbnail("abc", "Some subject") is None

"""Tests for app/services/culturetoon_media.py::save_image — content-type
allowlist, size limit, and (new) actual-image-content validation."""
import base64

import pytest

from app.services.culturetoon_media import save_image, ImageUploadError

# A real, minimal (1x1 transparent pixel) valid PNG.
_TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class TestSaveImage:
    def test_rejects_disallowed_content_type(self, mocker):
        mocker.patch("app.media.storage.upload")
        with pytest.raises(ImageUploadError, match="Unsupported content type"):
            save_image(_TINY_PNG_BYTES, "text/plain", "some/path.png")

    def test_rejects_empty_data(self, mocker):
        mocker.patch("app.media.storage.upload")
        with pytest.raises(ImageUploadError, match="No image data"):
            save_image(b"", "image/png", "some/path.png")

    def test_rejects_oversized_data(self, mocker):
        mocker.patch("app.media.storage.upload")
        with pytest.raises(ImageUploadError, match="exceeds 10MB"):
            save_image(b"x" * (10 * 1024 * 1024 + 1), "image/png", "some/path.png")

    def test_rejects_bytes_that_are_not_a_real_image_despite_correct_content_type(self, mocker):
        # The core regression this guards: a spoofed Content-Type header
        # (e.g. an uploaded script or SVG-with-script relabeled as
        # image/png) must not pass just because the client claims it's an
        # image — the bytes themselves have to actually decode as one.
        mock_upload = mocker.patch("app.media.storage.upload")
        with pytest.raises(ImageUploadError, match="not a valid image"):
            save_image(b"<script>alert(1)</script>", "image/png", "some/path.png")
        mock_upload.assert_not_called()

    def test_accepts_and_uploads_a_real_image(self, mocker):
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://storage.example/some/path.png")
        url = save_image(_TINY_PNG_BYTES, "image/png", "some/path.png")
        assert url == "https://storage.example/some/path.png"
        mock_upload.assert_called_once_with(_TINY_PNG_BYTES, "some/path.png", "image/png")

    def test_content_type_check_runs_before_image_decoding(self, mocker):
        # Disallowed content type should short-circuit even for garbage
        # bytes — confirms ordering didn't change (still cheap checks first).
        mocker.patch("app.media.storage.upload")
        with pytest.raises(ImageUploadError, match="Unsupported content type"):
            save_image(b"not an image at all", "application/octet-stream", "some/path.png")

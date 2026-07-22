import os
import pytest
from unittest.mock import Mock

os.environ.setdefault("TIKTOK_CLIENT_KEY", "test-client-key")
os.environ.setdefault("TIKTOK_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("OAUTH_REDIRECT_BASE_URL", "https://api.example.com")

from app.social.tiktok import TikTokProvider
from app.social.base import PostMetrics, TokenResult


class TestTikTokProviderConstruction:
    def test_missing_env_vars_raises(self, mocker):
        mocker.patch.dict(os.environ, {}, clear=True)
        with pytest.raises(RuntimeError):
            TikTokProvider()


class TestGetAuthorizeUrl:
    def test_includes_scopes_redirect_and_state(self):
        provider = TikTokProvider()
        url = provider.get_authorize_url(state="user-123:profile-456")
        assert url.startswith("https://www.tiktok.com/v2/auth/authorize/")
        assert "video.publish" in url
        assert "state=user-123" in url
        assert "redirect_uri=" in url
        assert "client_key=test-client-key" in url


class TestExchangeCode:
    def test_returns_token_result_with_username_and_open_id(self, mocker):
        token_resp = Mock(status_code=200)
        token_resp.json.return_value = {
            "access_token": "at-1", "refresh_token": "rt-1", "expires_in": 86400,
            "open_id": "open-id-123",
        }
        token_resp.raise_for_status = Mock()

        user_resp = Mock(status_code=200)
        user_resp.json.return_value = {"data": {"user": {"display_name": "My TikTok"}}}
        user_resp.raise_for_status = Mock()

        mocker.patch("app.social.tiktok.httpx.post", return_value=token_resp)
        mocker.patch("app.social.tiktok.httpx.get", return_value=user_resp)

        result = TikTokProvider().exchange_code("some-code")

        assert isinstance(result, TokenResult)
        assert result.access_token == "at-1"
        assert result.refresh_token == "rt-1"
        assert result.platform_account_id == "open-id-123"
        assert result.platform_username == "My TikTok"


class TestRefreshAccessToken:
    def test_reissues_refresh_token_unlike_google(self, mocker):
        # Google doesn't reissue refresh_token on refresh; TikTok does — this
        # is the one real behavioral divergence from YouTubeProvider's
        # refresh_access_token, worth pinning down explicitly.
        resp = Mock(status_code=200)
        resp.json.return_value = {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 86400}
        resp.raise_for_status = Mock()
        mocker.patch("app.social.tiktok.httpx.post", return_value=resp)

        result = TikTokProvider().refresh_access_token("rt-1")

        assert result.access_token == "at-2"
        assert result.refresh_token == "rt-2"


class TestFetchPostMetrics:
    def test_parses_video_id_and_stats_from_response(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {
            "data": {"videos": [{
                "id": "1234567890123456789", "view_count": 1000,
                "like_count": 50, "comment_count": 5, "share_count": 3,
            }]}
        }
        resp.raise_for_status = Mock()
        mocker.patch("app.social.tiktok.httpx.post", return_value=resp)

        metrics = TikTokProvider().fetch_post_metrics(
            "at-1", "https://www.tiktok.com/@someone/video/1234567890123456789"
        )

        assert isinstance(metrics, PostMetrics)
        assert metrics.platform_post_id == "1234567890123456789"
        assert metrics.views == 1000
        assert metrics.likes == 50
        assert metrics.comments == 5
        assert metrics.shares == 3

    def test_unrecognized_url_raises(self):
        with pytest.raises(ValueError):
            TikTokProvider().fetch_post_metrics("at-1", "https://example.com/not-a-video")

    def test_no_matching_video_raises(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {"data": {"videos": []}}
        resp.raise_for_status = Mock()
        mocker.patch("app.social.tiktok.httpx.post", return_value=resp)

        with pytest.raises(RuntimeError):
            TikTokProvider().fetch_post_metrics("at-1", "https://www.tiktok.com/@someone/video/999")


class TestPublish:
    def _mock_init_and_upload(self, mocker):
        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {
            "data": {"publish_id": "v_pub_file~v2-1.abc", "upload_url": "https://open-upload.tiktokapis.com/upload/"}
        }
        init_resp.raise_for_status = Mock()
        upload_resp = Mock(status_code=200)
        upload_resp.raise_for_status = Mock()
        mock_post = mocker.patch("app.social.tiktok.httpx.post", return_value=init_resp)
        mocker.patch("app.social.tiktok.httpx.put", return_value=upload_resp)
        return mock_post

    def test_returns_share_url_once_publish_completes(self, mocker):
        mocker.patch("app.social.tiktok.time.sleep")  # don't actually wait in tests
        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {
            "data": {"publish_id": "v_pub_file~v2-1.abc", "upload_url": "https://open-upload.tiktokapis.com/upload/"}
        }
        init_resp.raise_for_status = Mock()

        status_resp = Mock(status_code=200)
        status_resp.json.return_value = {
            "data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": ["987654321"]}
        }
        status_resp.raise_for_status = Mock()

        user_resp = Mock(status_code=200)
        user_resp.json.return_value = {"data": {"user": {"display_name": "creator"}}}
        user_resp.raise_for_status = Mock()

        # First POST call = init, second = user_info fetch happens via GET not
        # POST, third+ POST calls = status polling. Use side_effect ordering.
        mocker.patch("app.social.tiktok.httpx.post", side_effect=[init_resp, status_resp])
        mocker.patch("app.social.tiktok.httpx.get", return_value=user_resp)
        upload_resp = Mock(status_code=200)
        upload_resp.raise_for_status = Mock()
        mocker.patch("app.social.tiktok.httpx.put", return_value=upload_resp)

        metrics = TikTokProvider().publish("at-1", b"fake-video-bytes", "My Idea Hook", "Caption here")

        assert isinstance(metrics, PostMetrics)
        assert metrics.platform_post_id == "https://www.tiktok.com/@creator/video/987654321"
        assert metrics.views == 0

    def test_failed_status_raises_with_reason(self, mocker):
        mocker.patch("app.social.tiktok.time.sleep")
        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {
            "data": {"publish_id": "v_pub_file~v2-1.abc", "upload_url": "https://open-upload.tiktokapis.com/upload/"}
        }
        init_resp.raise_for_status = Mock()
        status_resp = Mock(status_code=200)
        status_resp.json.return_value = {"data": {"status": "FAILED", "fail_reason": "video_too_short"}}
        status_resp.raise_for_status = Mock()

        mocker.patch("app.social.tiktok.httpx.post", side_effect=[init_resp, status_resp])
        upload_resp = Mock(status_code=200)
        upload_resp.raise_for_status = Mock()
        mocker.patch("app.social.tiktok.httpx.put", return_value=upload_resp)

        with pytest.raises(RuntimeError, match="video_too_short"):
            TikTokProvider().publish("at-1", b"fake-video-bytes", "title", "desc")

    def test_never_completing_status_raises_after_max_attempts(self, mocker):
        mocker.patch("app.social.tiktok.time.sleep")
        mocker.patch("app.social.tiktok._STATUS_POLL_ATTEMPTS", 2)
        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {
            "data": {"publish_id": "v_pub_file~v2-1.abc", "upload_url": "https://open-upload.tiktokapis.com/upload/"}
        }
        init_resp.raise_for_status = Mock()
        processing_resp = Mock(status_code=200)
        processing_resp.json.return_value = {"data": {"status": "PROCESSING_UPLOAD"}}
        processing_resp.raise_for_status = Mock()

        mocker.patch("app.social.tiktok.httpx.post", side_effect=[init_resp, processing_resp, processing_resp])
        upload_resp = Mock(status_code=200)
        upload_resp.raise_for_status = Mock()
        mocker.patch("app.social.tiktok.httpx.put", return_value=upload_resp)

        with pytest.raises(RuntimeError, match="did not complete"):
            TikTokProvider().publish("at-1", b"fake-video-bytes", "title", "desc")

    def test_upload_uses_correct_content_range_header(self, mocker):
        mock_post = self._mock_init_and_upload(mocker)
        mocker.patch("app.social.tiktok.time.sleep")
        status_resp = Mock(status_code=200)
        status_resp.json.return_value = {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": ["1"]}}
        status_resp.raise_for_status = Mock()
        mock_post.side_effect = [mock_post.return_value, status_resp]

        mocker.patch("app.social.tiktok.httpx.get", return_value=Mock(
            status_code=200, json=lambda: {"data": {"user": {}}}, raise_for_status=Mock()
        ))
        mock_put = mocker.patch("app.social.tiktok.httpx.put")
        mock_put.return_value.raise_for_status = Mock()

        video_bytes = b"12345"
        TikTokProvider().publish("at-1", video_bytes, "title", "desc")

        assert mock_put.call_args.kwargs["headers"]["Content-Range"] == "bytes 0-4/5"

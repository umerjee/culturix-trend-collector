import os
import pytest
from unittest.mock import Mock

os.environ.setdefault("INSTAGRAM_CLIENT_ID", "test-client-id")
os.environ.setdefault("INSTAGRAM_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("OAUTH_REDIRECT_BASE_URL", "https://api.example.com")

from app.social.instagram import InstagramProvider
from app.social.base import PostMetrics, TokenResult


class TestInstagramProviderConstruction:
    def test_missing_env_vars_raises(self, mocker):
        mocker.patch.dict(os.environ, {}, clear=True)
        with pytest.raises(RuntimeError):
            InstagramProvider()


class TestGetAuthorizeUrl:
    def test_includes_business_scopes_and_state(self):
        provider = InstagramProvider()
        url = provider.get_authorize_url(state="user-123")
        assert url.startswith("https://www.instagram.com/oauth/authorize")
        assert "instagram_business_content_publish" in url
        assert "instagram_business_basic" in url
        assert "state=user-123" in url


class TestExchangeCode:
    def test_exchanges_short_lived_then_long_lived_and_fetches_username(self, mocker):
        short_resp = Mock(status_code=200)
        short_resp.json.return_value = {"access_token": "short-1", "user_id": 999}
        short_resp.raise_for_status = Mock()

        long_resp = Mock(status_code=200)
        long_resp.json.return_value = {"access_token": "long-1", "expires_in": 5184000}
        long_resp.raise_for_status = Mock()

        user_resp = Mock(status_code=200)
        user_resp.json.return_value = {"username": "my_ig_account"}
        user_resp.raise_for_status = Mock()

        mocker.patch("app.social.instagram.httpx.post", return_value=short_resp)
        mocker.patch("app.social.instagram.httpx.get", side_effect=[long_resp, user_resp])

        result = InstagramProvider().exchange_code("some-code")

        assert isinstance(result, TokenResult)
        assert result.access_token == "long-1"
        assert result.platform_account_id == "999"
        assert result.platform_username == "my_ig_account"
        assert result.refresh_token is None


class TestRefreshAccessToken:
    def test_returns_same_value_as_both_access_and_refresh_token(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {"access_token": "refreshed-1", "expires_in": 5184000}
        resp.raise_for_status = Mock()
        mocker.patch("app.social.instagram.httpx.get", return_value=resp)

        result = InstagramProvider().refresh_access_token("long-1")

        assert result.access_token == "refreshed-1"
        assert result.refresh_token == "refreshed-1"


class TestVerify:
    def test_returns_account_info_from_combined_me_call(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {"username": "my_ig_account", "user_id": 999}
        resp.raise_for_status = Mock()
        mock_get = mocker.patch("app.social.instagram.httpx.get", return_value=resp)

        info = InstagramProvider().verify("at-1")

        assert info.platform_account_id == "999"
        assert info.platform_username == "my_ig_account"
        # Combined into one call, not the two separate _fetch_username/_fetch_user_id calls.
        assert mock_get.call_count == 1
        assert mock_get.call_args.kwargs["params"]["fields"] == "username,user_id"

    def test_no_user_id_raises(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {"username": "my_ig_account"}
        resp.raise_for_status = Mock()
        mocker.patch("app.social.instagram.httpx.get", return_value=resp)

        with pytest.raises(RuntimeError):
            InstagramProvider().verify("at-1")


class TestFetchPostMetrics:
    def test_parses_own_media_id_fragment_and_stats(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {"like_count": 42, "comments_count": 7}
        resp.raise_for_status = Mock()
        mocker.patch("app.social.instagram.httpx.get", return_value=resp)

        metrics = InstagramProvider().fetch_post_metrics(
            "at-1", "https://www.instagram.com/reel/Cxyz123abc/#mid=17895695668004550"
        )

        assert isinstance(metrics, PostMetrics)
        assert metrics.platform_post_id == "17895695668004550"
        assert metrics.likes == 42
        assert metrics.comments == 7
        assert metrics.shares is None

    def test_url_without_own_fragment_raises_clear_error(self):
        with pytest.raises(ValueError, match="oEmbed"):
            InstagramProvider().fetch_post_metrics("at-1", "https://www.instagram.com/reel/Cxyz123abc/")


class TestPublish:
    def test_uploads_to_storage_then_creates_and_publishes_container(self, mocker):
        mocker.patch("app.social.instagram.time.sleep")
        mock_storage_upload = mocker.patch(
            "app.media.storage.upload", return_value="https://storage.example.com/video.mp4"
        )

        user_id_resp = Mock(status_code=200)
        user_id_resp.json.return_value = {"user_id": 999}
        user_id_resp.raise_for_status = Mock()

        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {"id": "container-1"}
        init_resp.raise_for_status = Mock()

        status_resp = Mock(status_code=200)
        status_resp.json.return_value = {"status_code": "FINISHED"}
        status_resp.raise_for_status = Mock()

        publish_resp = Mock(status_code=200)
        publish_resp.json.return_value = {"id": "17895695668004550"}
        publish_resp.raise_for_status = Mock()

        permalink_resp = Mock(status_code=200)
        permalink_resp.json.return_value = {"permalink": "https://www.instagram.com/reel/Cxyz123abc/"}
        permalink_resp.raise_for_status = Mock()

        mocker.patch("app.social.instagram.httpx.post", side_effect=[init_resp, publish_resp])
        mocker.patch("app.social.instagram.httpx.get", side_effect=[user_id_resp, status_resp, permalink_resp])

        metrics = InstagramProvider().publish("at-1", b"fake-video-bytes", "My Idea Hook", "Caption here")

        mock_storage_upload.assert_called_once()
        assert isinstance(metrics, PostMetrics)
        assert metrics.platform_post_id == "https://www.instagram.com/reel/Cxyz123abc/#mid=17895695668004550"

    def test_discloses_ai_generated_content(self, mocker):
        # Every video this codebase publishes is Kling-generated — must
        # always self-certify via is_ai_generated, unconditionally.
        mocker.patch("app.social.instagram.time.sleep")
        mocker.patch("app.media.storage.upload", return_value="https://storage.example.com/video.mp4")

        user_id_resp = Mock(status_code=200)
        user_id_resp.json.return_value = {"user_id": 999}
        user_id_resp.raise_for_status = Mock()
        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {"id": "container-1"}
        init_resp.raise_for_status = Mock()
        status_resp = Mock(status_code=200)
        status_resp.json.return_value = {"status_code": "FINISHED"}
        status_resp.raise_for_status = Mock()
        publish_resp = Mock(status_code=200)
        publish_resp.json.return_value = {"id": "17895695668004550"}
        publish_resp.raise_for_status = Mock()
        permalink_resp = Mock(status_code=200)
        permalink_resp.json.return_value = {"permalink": "https://www.instagram.com/reel/Cxyz123abc/"}
        permalink_resp.raise_for_status = Mock()

        mock_post = mocker.patch("app.social.instagram.httpx.post", side_effect=[init_resp, publish_resp])
        mocker.patch("app.social.instagram.httpx.get", side_effect=[user_id_resp, status_resp, permalink_resp])

        InstagramProvider().publish("at-1", b"fake-video-bytes", "title", "desc")

        init_call = mock_post.call_args_list[0]
        assert init_call.kwargs["data"]["is_ai_generated"] == "true"

    def test_container_error_status_raises(self, mocker):
        mocker.patch("app.social.instagram.time.sleep")
        mocker.patch("app.media.storage.upload", return_value="https://storage.example.com/video.mp4")

        user_id_resp = Mock(status_code=200)
        user_id_resp.json.return_value = {"user_id": 999}
        user_id_resp.raise_for_status = Mock()
        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {"id": "container-1"}
        init_resp.raise_for_status = Mock()
        status_resp = Mock(status_code=200)
        status_resp.json.return_value = {"status_code": "ERROR"}
        status_resp.raise_for_status = Mock()

        mocker.patch("app.social.instagram.httpx.post", return_value=init_resp)
        mocker.patch("app.social.instagram.httpx.get", side_effect=[user_id_resp, status_resp])

        with pytest.raises(RuntimeError, match="failed to process"):
            InstagramProvider().publish("at-1", b"fake-video-bytes", "title", "desc")

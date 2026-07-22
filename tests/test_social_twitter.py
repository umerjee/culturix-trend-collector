import os
import pytest
from unittest.mock import Mock

os.environ.setdefault("TWITTER_CLIENT_ID", "test-client-id")
os.environ.setdefault("TWITTER_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("OAUTH_REDIRECT_BASE_URL", "https://api.example.com")

from app.social.twitter import TwitterProvider, _CODE_CHALLENGE, _CODE_VERIFIER
from app.social.base import PostMetrics, TokenResult


class TestTwitterProviderConstruction:
    def test_missing_env_vars_raises(self, mocker):
        mocker.patch.dict(os.environ, {}, clear=True)
        with pytest.raises(RuntimeError):
            TwitterProvider()


class TestPkcePair:
    def test_challenge_is_deterministic_sha256_of_fixed_verifier(self):
        import base64, hashlib
        expected = base64.urlsafe_b64encode(hashlib.sha256(_CODE_VERIFIER.encode()).digest()).decode().rstrip("=")
        assert _CODE_CHALLENGE == expected


class TestGetAuthorizeUrl:
    def test_includes_pkce_challenge_scopes_and_state(self):
        provider = TwitterProvider()
        url = provider.get_authorize_url(state="user-123")
        assert url.startswith("https://twitter.com/i/oauth2/authorize")
        assert f"code_challenge={_CODE_CHALLENGE}" in url
        assert "code_challenge_method=S256" in url
        assert "tweet.write" in url
        assert "offline.access" in url
        assert "state=user-123" in url


class TestExchangeCode:
    def test_sends_code_verifier_and_basic_auth_then_fetches_username(self, mocker):
        token_resp = Mock(status_code=200)
        token_resp.json.return_value = {
            "access_token": "at-1", "refresh_token": "rt-1", "expires_in": 7200,
        }
        token_resp.raise_for_status = Mock()
        mock_post = mocker.patch("app.social.twitter.httpx.post", return_value=token_resp)

        user_resp = Mock(status_code=200)
        user_resp.json.return_value = {"data": {"username": "my_x_handle"}}
        user_resp.raise_for_status = Mock()
        mocker.patch("app.social.twitter.httpx.get", return_value=user_resp)

        result = TwitterProvider().exchange_code("some-code")

        assert isinstance(result, TokenResult)
        assert result.access_token == "at-1"
        assert result.refresh_token == "rt-1"
        assert result.platform_username == "my_x_handle"
        assert mock_post.call_args.kwargs["data"]["code_verifier"] == _CODE_VERIFIER
        assert mock_post.call_args.kwargs["auth"] == ("test-client-id", "test-client-secret")


class TestFetchPostMetrics:
    def test_parses_tweet_id_and_public_metrics(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {
            "data": {
                "id": "1234567890123456789",
                "public_metrics": {
                    "impression_count": 5000, "like_count": 120,
                    "reply_count": 8, "retweet_count": 15,
                },
            }
        }
        resp.raise_for_status = Mock()
        mocker.patch("app.social.twitter.httpx.get", return_value=resp)

        metrics = TwitterProvider().fetch_post_metrics(
            "at-1", "https://x.com/someone/status/1234567890123456789"
        )

        assert isinstance(metrics, PostMetrics)
        assert metrics.platform_post_id == "1234567890123456789"
        assert metrics.views == 5000
        assert metrics.likes == 120
        assert metrics.comments == 8
        assert metrics.shares == 15

    def test_unrecognized_url_raises(self):
        with pytest.raises(ValueError):
            TwitterProvider().fetch_post_metrics("at-1", "https://example.com/not-a-tweet")

    def test_no_matching_tweet_raises(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {}
        resp.raise_for_status = Mock()
        mocker.patch("app.social.twitter.httpx.get", return_value=resp)

        with pytest.raises(RuntimeError):
            TwitterProvider().fetch_post_metrics("at-1", "https://x.com/someone/status/999")


class TestPublish:
    def test_single_chunk_upload_with_no_processing_needed(self, mocker):
        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {"media_id_string": "media-1"}
        init_resp.raise_for_status = Mock()
        append_resp = Mock(status_code=200)
        append_resp.raise_for_status = Mock()
        finalize_resp = Mock(status_code=200)
        finalize_resp.json.return_value = {"media_id_string": "media-1"}  # no processing_info — image-like, immediate
        finalize_resp.raise_for_status = Mock()
        tweet_resp = Mock(status_code=200)
        tweet_resp.json.return_value = {"data": {"id": "999888777"}}
        tweet_resp.raise_for_status = Mock()

        mocker.patch(
            "app.social.twitter.httpx.post",
            side_effect=[init_resp, append_resp, finalize_resp, tweet_resp],
        )

        metrics = TwitterProvider().publish("at-1", b"small-video-bytes", "hook", "caption text")

        assert isinstance(metrics, PostMetrics)
        assert metrics.platform_post_id == "999888777"

    def test_video_processing_polled_until_succeeded(self, mocker):
        mocker.patch("app.social.twitter.time.sleep")
        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {"media_id_string": "media-1"}
        init_resp.raise_for_status = Mock()
        append_resp = Mock(status_code=200)
        append_resp.raise_for_status = Mock()
        finalize_resp = Mock(status_code=200)
        finalize_resp.json.return_value = {
            "media_id_string": "media-1",
            "processing_info": {"state": "pending", "check_after_secs": 1},
        }
        finalize_resp.raise_for_status = Mock()
        status_resp = Mock(status_code=200)
        status_resp.json.return_value = {"processing_info": {"state": "succeeded"}}
        status_resp.raise_for_status = Mock()
        tweet_resp = Mock(status_code=200)
        tweet_resp.json.return_value = {"data": {"id": "999888777"}}
        tweet_resp.raise_for_status = Mock()

        mocker.patch(
            "app.social.twitter.httpx.post",
            side_effect=[init_resp, append_resp, finalize_resp, tweet_resp],
        )
        mocker.patch("app.social.twitter.httpx.get", return_value=status_resp)

        metrics = TwitterProvider().publish("at-1", b"video-bytes", "hook", "caption")

        assert metrics.platform_post_id == "999888777"

    def test_processing_failure_raises(self, mocker):
        mocker.patch("app.social.twitter.time.sleep")
        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {"media_id_string": "media-1"}
        init_resp.raise_for_status = Mock()
        append_resp = Mock(status_code=200)
        append_resp.raise_for_status = Mock()
        finalize_resp = Mock(status_code=200)
        finalize_resp.json.return_value = {
            "media_id_string": "media-1",
            "processing_info": {"state": "failed", "error": {"message": "invalid video"}},
        }
        finalize_resp.raise_for_status = Mock()

        mocker.patch("app.social.twitter.httpx.post", side_effect=[init_resp, append_resp, finalize_resp])

        with pytest.raises(RuntimeError, match="failed"):
            TwitterProvider().publish("at-1", b"video-bytes", "hook", "caption")

    def test_large_video_uploads_in_multiple_append_chunks(self, mocker):
        from app.social.twitter import _APPEND_CHUNK_SIZE

        init_resp = Mock(status_code=200)
        init_resp.json.return_value = {"media_id_string": "media-1"}
        init_resp.raise_for_status = Mock()
        append_resp = Mock(status_code=200)
        append_resp.raise_for_status = Mock()
        finalize_resp = Mock(status_code=200)
        finalize_resp.json.return_value = {"media_id_string": "media-1"}
        finalize_resp.raise_for_status = Mock()
        tweet_resp = Mock(status_code=200)
        tweet_resp.json.return_value = {"data": {"id": "1"}}
        tweet_resp.raise_for_status = Mock()

        mock_post = mocker.patch(
            "app.social.twitter.httpx.post",
            side_effect=[init_resp, append_resp, append_resp, finalize_resp, tweet_resp],
        )

        big_video = b"x" * (_APPEND_CHUNK_SIZE + 100)
        TwitterProvider().publish("at-1", big_video, "hook", "caption")

        append_calls = [c for c in mock_post.call_args_list if c.kwargs.get("data", {}).get("command") == "APPEND"]
        assert len(append_calls) == 2
        assert append_calls[0].kwargs["data"]["segment_index"] == 0
        assert append_calls[1].kwargs["data"]["segment_index"] == 1

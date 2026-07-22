import os
import pytest
from unittest.mock import Mock

os.environ.setdefault("YOUTUBE_OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("YOUTUBE_OAUTH_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("OAUTH_REDIRECT_BASE_URL", "https://api.example.com")

from app.social.youtube import YouTubeProvider, _parse_video_id
from app.social.base import PostMetrics, TokenResult


class TestParseVideoId:
    def test_watch_url(self):
        assert _parse_video_id("https://www.youtube.com/watch?v=abc123DEF45") == "abc123DEF45"

    def test_short_url(self):
        assert _parse_video_id("https://youtu.be/abc123DEF45") == "abc123DEF45"

    def test_shorts_url(self):
        assert _parse_video_id("https://www.youtube.com/shorts/abc123DEF45") == "abc123DEF45"

    def test_unrecognized_url_raises(self):
        with pytest.raises(ValueError):
            _parse_video_id("https://example.com/not-a-video")


class TestYouTubeProviderConstruction:
    def test_missing_env_vars_raises(self, mocker):
        mocker.patch.dict(os.environ, {}, clear=True)
        with pytest.raises(RuntimeError):
            YouTubeProvider()


class TestGetAuthorizeUrl:
    def test_includes_both_scopes_and_state(self):
        provider = YouTubeProvider()
        url = provider.get_authorize_url(state="user-123")
        assert "youtube.readonly" in url
        assert "youtube.upload" in url
        assert "state=user-123" in url
        assert "access_type=offline" in url


class TestExchangeCode:
    def test_returns_token_result_with_channel_identity(self, mocker):
        token_resp = Mock(status_code=200)
        token_resp.json.return_value = {
            "access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600,
        }
        token_resp.raise_for_status = Mock()

        channel_resp = Mock(status_code=200)
        channel_resp.json.return_value = {"items": [{"id": "UC123", "snippet": {"title": "My Channel"}}]}
        channel_resp.raise_for_status = Mock()

        mocker.patch("app.social.youtube.httpx.post", return_value=token_resp)
        mocker.patch("app.social.youtube.httpx.get", return_value=channel_resp)

        result = YouTubeProvider().exchange_code("some-code")

        assert isinstance(result, TokenResult)
        assert result.access_token == "at-1"
        assert result.refresh_token == "rt-1"
        assert result.platform_account_id == "UC123"
        assert result.platform_username == "My Channel"


class TestFetchPostMetrics:
    def test_parses_statistics_from_response(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {
            "items": [{"statistics": {"viewCount": "1000", "likeCount": "50", "commentCount": "5"}}]
        }
        resp.raise_for_status = Mock()
        mocker.patch("app.social.youtube.httpx.get", return_value=resp)

        metrics = YouTubeProvider().fetch_post_metrics("at-1", "https://youtu.be/abc123DEF45")

        assert isinstance(metrics, PostMetrics)
        assert metrics.platform_post_id == "abc123DEF45"
        assert metrics.views == 1000
        assert metrics.likes == 50
        assert metrics.comments == 5
        assert metrics.shares is None  # YouTube's public Data API has no share count

    def test_no_matching_video_raises(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {"items": []}
        resp.raise_for_status = Mock()
        mocker.patch("app.social.youtube.httpx.get", return_value=resp)

        with pytest.raises(RuntimeError):
            YouTubeProvider().fetch_post_metrics("at-1", "https://youtu.be/abc123DEF45")


class TestPublish:
    def test_returns_new_video_id_with_zeroed_metrics(self, mocker):
        resp = Mock(status_code=200)
        resp.json.return_value = {"id": "newVideoId1"}
        resp.raise_for_status = Mock()
        mock_post = mocker.patch("app.social.youtube.httpx.post", return_value=resp)

        metrics = YouTubeProvider().publish(
            "at-1", b"fake-video-bytes", title="My Idea Hook", description="Caption here"
        )

        assert metrics.platform_post_id == "newVideoId1"
        assert metrics.views == 0
        assert metrics.likes == 0
        assert metrics.comments == 0
        # Confirm the upload actually included the video bytes
        sent_body = mock_post.call_args.kwargs["content"]
        assert b"fake-video-bytes" in sent_body

    def test_discloses_ai_generated_content(self, mocker):
        # Every video this codebase publishes is Kling-generated — must
        # always self-certify via containsSyntheticMedia, unconditionally.
        resp = Mock(status_code=200)
        resp.json.return_value = {"id": "newVideoId1"}
        resp.raise_for_status = Mock()
        mock_post = mocker.patch("app.social.youtube.httpx.post", return_value=resp)

        YouTubeProvider().publish("at-1", b"fake-video-bytes", title="title", description="desc")

        sent_body = mock_post.call_args.kwargs["content"]
        assert b'"containsSyntheticMedia": true' in sent_body

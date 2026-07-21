import json
import os

import pytest

from app.account_suggestions import generate_account_suggestions, _parse_response, _build_prompt

_SAMPLE_RESPONSE = {
    "recommended_platforms": [{"platform": "TikTok", "reason": "Short-form fits the niche"}],
    "name_suggestions": [{"name": "GlowRitual", "reason": "Evokes routine + radiance"}],
    "bio_suggestion": "Daily glow-up rituals for your skin and soul ✨",
}


def _profile(**overrides):
    base = {
        "industry_niche": "beauty and self-care",
        "target_platforms": ["TikTok", "Instagram"],
        "content_goals": ["Brand awareness"],
        "content_tones": ["Authentic & raw"],
        "persona_tags": ["Clean Girl"],
    }
    base.update(overrides)
    return base


class TestBuildPrompt:
    def test_includes_niche_and_platforms(self):
        prompt = _build_prompt(_profile())
        assert "beauty and self-care" in prompt
        assert "TikTok, Instagram" in prompt

    def test_missing_platforms_falls_back_to_general_recommendation_language(self):
        prompt = _build_prompt(_profile(target_platforms=[]))
        assert "no specific platform chosen yet" in prompt


class TestParseResponse:
    def test_parses_plain_json(self):
        assert _parse_response(json.dumps(_SAMPLE_RESPONSE)) == _SAMPLE_RESPONSE

    def test_strips_markdown_json_fence(self):
        raw = f"```json\n{json.dumps(_SAMPLE_RESPONSE)}\n```"
        assert _parse_response(raw) == _SAMPLE_RESPONSE

    def test_strips_plain_markdown_fence(self):
        raw = f"```\n{json.dumps(_SAMPLE_RESPONSE)}\n```"
        assert _parse_response(raw) == _SAMPLE_RESPONSE


class TestGenerateAccountSuggestions:
    def test_uses_qwen_when_key_present(self, mocker):
        mocker.patch.dict(os.environ, {"QWEN_API_KEY": "test-key"})
        mock_client = mocker.Mock()
        mock_client.chat.completions.create.return_value.choices = [
            mocker.Mock(message=mocker.Mock(content=json.dumps(_SAMPLE_RESPONSE)))
        ]
        mocker.patch("app.account_suggestions._get_qwen_client", return_value=mock_client)
        mock_claude = mocker.patch("app.account_suggestions._get_claude_client")

        result = generate_account_suggestions(_profile())

        assert result == _SAMPLE_RESPONSE
        mock_client.chat.completions.create.assert_called_once()
        assert mock_client.chat.completions.create.call_args.kwargs["model"] == "qwen-max"
        mock_claude.assert_not_called()

    def test_falls_back_to_claude_when_no_qwen_key(self, mocker):
        mocker.patch.dict(os.environ, {}, clear=True)
        mock_client = mocker.Mock()
        mock_client.messages.create.return_value.content = [
            mocker.Mock(text=json.dumps(_SAMPLE_RESPONSE))
        ]
        mocker.patch("app.account_suggestions._get_claude_client", return_value=mock_client)

        result = generate_account_suggestions(_profile())

        assert result == _SAMPLE_RESPONSE
        mock_client.messages.create.assert_called_once()
        assert mock_client.messages.create.call_args.kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_malformed_json_response_raises(self, mocker):
        mocker.patch.dict(os.environ, {"QWEN_API_KEY": "test-key"})
        mock_client = mocker.Mock()
        mock_client.chat.completions.create.return_value.choices = [
            mocker.Mock(message=mocker.Mock(content="not valid json"))
        ]
        mocker.patch("app.account_suggestions._get_qwen_client", return_value=mock_client)

        with pytest.raises(json.JSONDecodeError):
            generate_account_suggestions(_profile())

from unittest.mock import Mock, MagicMock

from app.shopify.content_ideas import generate_product_post_idea

_PRODUCT = {
    "title": "Embroidered Kurta",
    "description": "Hand-embroidered cotton kurta in emerald green.",
    "product_type": "Kurta",
    "tags": "eid, new-arrival",
    "price": "45.00",
    "currency": "USD",
}

_FAKE_IDEA_JSON = """{
    "hook": "This emerald kurta is the Eid piece everyone will ask about",
    "caption": "Hand-embroidered, made to be worn on repeat. #eidfashion #kurta #handmade #emeraldgreen #ootd",
    "cta": "Shop the link in bio",
    "hashtag_strategy": "#eidfashion #kurta #handmade #emeraldgreen #ootd",
    "platform": "Instagram"
}"""


class TestGenerateProductPostIdea:
    def test_uses_qwen_when_key_present(self, mocker, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = Mock(
            choices=[Mock(message=Mock(content=_FAKE_IDEA_JSON))]
        )
        mocker.patch("app.shopify.content_ideas._get_qwen_client", return_value=mock_client)

        idea = generate_product_post_idea(_PRODUCT)

        assert idea["hook"].startswith("This emerald kurta")
        assert idea["platform"] == "Instagram"
        sent_prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Embroidered Kurta" in sent_prompt
        assert "45.00 USD" in sent_prompt

    def test_falls_back_to_claude_when_no_qwen_key(self, mocker, monkeypatch):
        monkeypatch.delenv("QWEN_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = Mock(content=[Mock(text=_FAKE_IDEA_JSON)])
        mocker.patch("app.shopify.content_ideas._get_claude_client", return_value=mock_client)

        idea = generate_product_post_idea(_PRODUCT)

        assert idea["cta"] == "Shop the link in bio"

    def test_strips_markdown_code_fences(self, mocker, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = Mock(
            choices=[Mock(message=Mock(content=f"```json\n{_FAKE_IDEA_JSON}\n```"))]
        )
        mocker.patch("app.shopify.content_ideas._get_qwen_client", return_value=mock_client)

        idea = generate_product_post_idea(_PRODUCT)
        assert idea["platform"] == "Instagram"

    def test_handles_missing_price(self, mocker, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = Mock(
            choices=[Mock(message=Mock(content=_FAKE_IDEA_JSON))]
        )
        mocker.patch("app.shopify.content_ideas._get_qwen_client", return_value=mock_client)

        generate_product_post_idea({"title": "Mystery Item"})
        sent_prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "unknown" in sent_prompt

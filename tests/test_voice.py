from app.media.voice import _strip_emoji


class TestStripEmoji:
    def test_removes_trailing_emoji(self):
        assert _strip_emoji("Trea Turner's latest move has fans buzzing! 🏃🔥") == \
            "Trea Turner's latest move has fans buzzing!"

    def test_removes_emoji_in_middle_without_leaving_double_spaces(self):
        assert _strip_emoji("This is 🔥 amazing news") == "This is amazing news"

    def test_removes_multiple_scattered_emoji(self):
        result = _strip_emoji("🎉 Big news! 🚀 Everyone's talking about it 💯")
        assert "🎉" not in result and "🚀" not in result and "💯" not in result
        assert result == "Big news! Everyone's talking about it"

    def test_leaves_plain_text_unchanged(self):
        assert _strip_emoji("This is a normal sentence with no emoji.") == \
            "This is a normal sentence with no emoji."

    def test_leaves_punctuation_and_numbers_intact(self):
        assert _strip_emoji("Top 10 reasons why #1 matters!") == "Top 10 reasons why #1 matters!"

    def test_handles_empty_string(self):
        assert _strip_emoji("") == ""

    def test_handles_all_emoji_string(self):
        assert _strip_emoji("🔥🔥🔥") == ""

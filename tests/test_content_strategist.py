import json
import os

import pytest

from app.pipeline.nodes.content_strategist import (
    PROACTIVE_CLUSTER_COUNT,
    _build_prompt,
    _generate_ideas_for_clusters,
    generate_content,
)

_SAMPLE_IDEA = {
    "hook": "Paul Mescal in The Mummy reboot", "caption": "...", "cta": "...",
    "music_mood": "Epic cinematic", "platform": "Instagram", "trend_connection": "The Mummy reboot casting",
    "format": "carousel", "video_prompt": "...", "viral_angle": "hot take",
    "posting_time": "Friday 5-7pm", "hashtag_strategy": "#a #b #c #d #e",
}


def _cluster(name: str) -> dict:
    return {"name": name, "description": "...", "emotional_theme": "curiosity", "example_posts": ["a post"]}


class TestBuildPrompt:
    def test_asks_for_exactly_one_idea_per_cluster_count(self):
        clusters = [_cluster("A"), _cluster("B"), _cluster("C")]
        prompt = _build_prompt({}, clusters)
        assert "EXACTLY 3" in prompt

    def test_includes_example_posts_for_grounding(self):
        clusters = [{"name": "X", "description": "d", "emotional_theme": "e", "example_posts": ["real post text"]}]
        prompt = _build_prompt({}, clusters)
        assert "real post text" in prompt

    def test_empty_preferred_formats_defaults_to_all_three_media(self):
        prompt = _build_prompt({"preferred_formats": []}, [_cluster("A")])
        assert "video" in prompt and "photo" in prompt and "text" in prompt

    def test_missing_preferred_formats_key_defaults_to_all_three_media(self):
        prompt = _build_prompt({}, [_cluster("A")])
        assert "video" in prompt and "photo" in prompt and "text" in prompt

    def test_restricted_preferred_formats_excludes_other_media_styles(self):
        # GRWM/thread only ever appear in the allowed-styles reference list built
        # from _MEDIUM_STYLES — unlike "duet"/"challenge", which also appear in
        # unrelated instructional text explaining the video-only-mechanics rule
        # itself, so they're not safe markers for "was this style offered."
        prompt = _build_prompt({"preferred_formats": ["photo"]}, [_cluster("A")])
        assert "carousel" in prompt  # a photo-medium style
        assert "GRWM" not in prompt  # a video-only style should not be offered
        assert "thread" not in prompt  # a text-only style should not be offered


class TestGenerateIdeasForClusters:
    def test_empty_clusters_returns_empty_without_calling_any_client(self, mocker):
        mock_qwen = mocker.patch("app.pipeline.nodes.content_strategist._get_qwen_client")
        mock_claude = mocker.patch("app.pipeline.nodes.content_strategist._get_claude_client")
        result = _generate_ideas_for_clusters({}, [])
        assert result == []
        mock_qwen.assert_not_called()
        mock_claude.assert_not_called()

    def test_uses_qwen_when_key_present(self, mocker):
        mocker.patch.dict(os.environ, {"QWEN_API_KEY": "test-key"})
        mock_client = mocker.Mock()
        mock_client.chat.completions.create.return_value.choices = [
            mocker.Mock(message=mocker.Mock(content=json.dumps([_SAMPLE_IDEA])))
        ]
        mocker.patch("app.pipeline.nodes.content_strategist._get_qwen_client", return_value=mock_client)

        result = _generate_ideas_for_clusters({}, [_cluster("A")])

        assert len(result) == 1
        assert result[0]["hook"] == _SAMPLE_IDEA["hook"]
        mock_client.chat.completions.create.assert_called_once()
        assert mock_client.chat.completions.create.call_args.kwargs["model"] == "qwen-max"

    def test_falls_back_to_claude_when_no_qwen_key(self, mocker):
        mocker.patch.dict(os.environ, {}, clear=True)
        mock_client = mocker.Mock()
        mock_client.messages.create.return_value.content = [mocker.Mock(text=json.dumps([_SAMPLE_IDEA]))]
        mocker.patch("app.pipeline.nodes.content_strategist._get_claude_client", return_value=mock_client)

        result = _generate_ideas_for_clusters({}, [_cluster("A")])

        assert len(result) == 1
        mock_client.messages.create.assert_called_once()

    def test_returns_ideas_in_same_order_as_clusters(self, mocker):
        mocker.patch.dict(os.environ, {"QWEN_API_KEY": "test-key"})
        idea_a = {**_SAMPLE_IDEA, "hook": "idea for A"}
        idea_b = {**_SAMPLE_IDEA, "hook": "idea for B"}
        mock_client = mocker.Mock()
        mock_client.chat.completions.create.return_value.choices = [
            mocker.Mock(message=mocker.Mock(content=json.dumps([idea_a, idea_b])))
        ]
        mocker.patch("app.pipeline.nodes.content_strategist._get_qwen_client", return_value=mock_client)

        result = _generate_ideas_for_clusters({}, [_cluster("A"), _cluster("B")])

        assert result[0]["hook"] == "idea for A"
        assert result[1]["hook"] == "idea for B"


class TestGenerateContent:
    def test_only_sends_top_n_clusters_to_generation(self, mocker):
        clusters = [_cluster(str(i)) for i in range(6)]
        mock_generate = mocker.patch(
            "app.pipeline.nodes.content_strategist._generate_ideas_for_clusters",
            return_value=[dict(_SAMPLE_IDEA) for _ in range(PROACTIVE_CLUSTER_COUNT)],
        )
        state = {"persona_matches": [
            {"user_id": "u1", "profile": {}, "clusters": clusters, "top_signals": []},
        ]}

        generate_content(state)

        sent_clusters = mock_generate.call_args.args[1]
        assert len(sent_clusters) == PROACTIVE_CLUSTER_COUNT
        assert sent_clusters == clusters[:PROACTIVE_CLUSTER_COUNT]

    def test_tags_each_idea_with_cluster_index_and_auto_source(self, mocker):
        clusters = [_cluster("A"), _cluster("B"), _cluster("C")]
        mocker.patch(
            "app.pipeline.nodes.content_strategist._generate_ideas_for_clusters",
            return_value=[dict(_SAMPLE_IDEA), dict(_SAMPLE_IDEA), dict(_SAMPLE_IDEA)],
        )
        state = {"persona_matches": [
            {"user_id": "u1", "profile": {}, "clusters": clusters, "top_signals": []},
        ]}

        result = generate_content(state)

        ideas = result["generated_content"][0]["ideas"]
        assert [i["cluster_index"] for i in ideas] == [0, 1, 2]
        assert all(i["source"] == "auto" for i in ideas)

    def test_full_cluster_list_is_stored_not_just_the_proactive_subset(self, mocker):
        clusters = [_cluster(str(i)) for i in range(6)]
        mocker.patch(
            "app.pipeline.nodes.content_strategist._generate_ideas_for_clusters",
            return_value=[dict(_SAMPLE_IDEA) for _ in range(PROACTIVE_CLUSTER_COUNT)],
        )
        state = {"persona_matches": [
            {"user_id": "u1", "profile": {}, "clusters": clusters, "top_signals": []},
        ]}

        result = generate_content(state)

        assert result["generated_content"][0]["clusters"] == clusters

    def test_generation_failure_for_one_profile_is_recorded_and_others_continue(self, mocker):
        mocker.patch(
            "app.pipeline.nodes.content_strategist._generate_ideas_for_clusters",
            side_effect=[RuntimeError("API down"), [dict(_SAMPLE_IDEA)]],
        )
        state = {"persona_matches": [
            {"user_id": "u1", "profile": {}, "clusters": [_cluster("A")], "top_signals": []},
            {"user_id": "u2", "profile": {}, "clusters": [_cluster("B")], "top_signals": []},
        ]}

        result = generate_content(state)

        assert len(result["generated_content"]) == 1
        assert result["generated_content"][0]["user_id"] == "u2"
        assert any("content_gen:u1" in e for e in result["errors"])

    def test_no_persona_matches_short_circuits(self, mocker):
        mock_generate = mocker.patch("app.pipeline.nodes.content_strategist._generate_ideas_for_clusters")
        state = {"persona_matches": []}

        result = generate_content(state)

        assert result["generated_content"] == []
        mock_generate.assert_not_called()

"""Tests for app/services/culturetoon_qa.py — technical/visual deterministic
checks (Phase 7a) and AI-judge comedy/cultural scoring (Phase 7b). LLM calls
are always mocked here — see test_culturetoon_video.py's autouse fixture for
why (real QWEN_API_KEY/ANTHROPIC_API_KEY are present via .env)."""
import json
import os
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.services.culturetoon_qa import (
    run_technical_qa, run_ai_judge_qa, run_full_qa,
    PUBLISH_OVERALL_THRESHOLD, PUBLISH_CULTURAL_THRESHOLD, PUBLISH_TECHNICAL_THRESHOLD,
)


def _fake_probe(duration=15.0, width=1080, height=1920, has_audio=True):
    streams = [{"codec_type": "video", "width": width, "height": height}]
    if has_audio:
        streams.append({"codec_type": "audio"})
    return {"format": {"duration": str(duration)}, "streams": streams}


class TestRunTechnicalQA:
    def test_all_checks_pass(self, mocker):
        mocker.patch("ffmpeg.probe", return_value=_fake_probe(duration=15.0))
        result = run_technical_qa("fake.mp4", expected_duration_seconds=15.0, expected_aspect_ratio="9:16")
        assert result["file_integrity_ok"] is True
        assert result["duration_ok"] is True
        assert result["aspect_ratio_ok"] is True
        assert result["audio_present"] is True
        assert result["technical_score"] == 100
        assert result["issues"] == []

    def test_probe_failure_scores_zero(self, mocker):
        mocker.patch("ffmpeg.probe", side_effect=RuntimeError("invalid data"))
        result = run_technical_qa("corrupt.mp4", expected_duration_seconds=15.0)
        assert result["file_integrity_ok"] is False
        assert result["technical_score"] == 0
        assert "corrupt" in result["issues"][0].lower() or "invalid data" in result["issues"][0]

    def test_duration_mismatch_flagged(self, mocker):
        mocker.patch("ffmpeg.probe", return_value=_fake_probe(duration=5.0))
        result = run_technical_qa("fake.mp4", expected_duration_seconds=15.0)
        assert result["duration_ok"] is False
        assert result["technical_score"] < 100
        assert any("Duration" in issue for issue in result["issues"])

    def test_duration_within_tolerance_passes(self, mocker):
        # 15s expected, tolerance = max(2, 15*0.25) = 3.75s -> 12s is within tolerance
        mocker.patch("ffmpeg.probe", return_value=_fake_probe(duration=12.0))
        result = run_technical_qa("fake.mp4", expected_duration_seconds=15.0)
        assert result["duration_ok"] is True

    def test_wrong_aspect_ratio_flagged(self, mocker):
        mocker.patch("ffmpeg.probe", return_value=_fake_probe(width=1920, height=1080))  # 16:9, not 9:16
        result = run_technical_qa("fake.mp4", expected_duration_seconds=15.0, expected_aspect_ratio="9:16")
        assert result["aspect_ratio_ok"] is False
        assert any("aspect ratio" in issue.lower() for issue in result["issues"])

    def test_no_audio_flagged(self, mocker):
        mocker.patch("ffmpeg.probe", return_value=_fake_probe(has_audio=False))
        result = run_technical_qa("fake.mp4", expected_duration_seconds=15.0)
        assert result["audio_present"] is False
        assert any("audio" in issue.lower() for issue in result["issues"])


class TestRunAiJudgeQA:
    def _mock_qwen(self, mocker, payload: dict):
        os.environ["QWEN_API_KEY"] = "test-key"
        fake_message = mocker.Mock()
        fake_message.content = json.dumps(payload)
        fake_choice = mocker.Mock()
        fake_choice.message = fake_message
        fake_response = mocker.Mock()
        fake_response.choices = [fake_choice]
        fake_client = mocker.Mock()
        fake_client.chat.completions.create.return_value = fake_response
        mocker.patch("openai.OpenAI", return_value=fake_client)
        return fake_client

    def test_well_formed_response_parsed(self, mocker):
        self._mock_qwen(mocker, {
            "comedy_score": 85, "cultural_score": 90,
            "cultural_concerns": [], "reasoning": "Good pacing.",
        })
        result = run_ai_judge_qa("Hook", "funny", [{"shot_number": 1, "action": "waves", "dialogue": "Hi"}], [])
        assert result["comedy_score"] == 85
        assert result["cultural_score"] == 90
        assert result["judge_failed"] is False

    def test_cultural_guardrails_included_in_prompt(self, mocker):
        fake_client = self._mock_qwen(mocker, {"comedy_score": 50, "cultural_score": 50, "cultural_concerns": []})
        run_ai_judge_qa(
            "Hook", "funny", [{"shot_number": 1, "action": "does a thing"}],
            [{"name": "Indian", "stereotypes_to_avoid": ["accent mockery", "call-center caricature"]}],
        )
        sent_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "accent mockery" in sent_prompt
        assert "call-center caricature" in sent_prompt

    def test_llm_failure_returns_neutral_placeholder_not_raise(self, mocker):
        os.environ["QWEN_API_KEY"] = "test-key"
        mocker.patch("openai.OpenAI", side_effect=RuntimeError("provider down"))
        result = run_ai_judge_qa("Hook", "funny", [], [])
        assert result["judge_failed"] is True
        assert result["comedy_score"] == 50  # neutral placeholder, not a real assessment
        assert "placeholder" in result["reasoning"].lower()


class TestRunFullQA:
    def test_combines_technical_and_judge_scores(self, mocker):
        mocker.patch("ffmpeg.probe", return_value=_fake_probe(duration=15.0))
        mocker.patch(
            "app.services.culturetoon_qa.run_ai_judge_qa",
            return_value={"comedy_score": 90, "cultural_score": 95, "cultural_concerns": [], "reasoning": "r", "judge_failed": False},
        )
        result = run_full_qa("fake.mp4", 15.0, "Hook", "funny", [{"shot_number": 1, "action": "x"}], [])

        assert result["technical_score"] == 100
        assert result["visual_score"] == 100  # documented as == technical_score, not independent
        assert result["comedy_score"] == 90
        assert result["cultural_score"] == 95
        assert result["overall_score"] == round((100 + 90 + 95 + 100) / 4)
        assert result["publish_recommended"] is True

    def test_low_technical_score_blocks_publish_recommendation(self, mocker):
        mocker.patch("ffmpeg.probe", side_effect=RuntimeError("corrupt"))
        mocker.patch(
            "app.services.culturetoon_qa.run_ai_judge_qa",
            return_value={"comedy_score": 95, "cultural_score": 95, "cultural_concerns": [], "reasoning": "r", "judge_failed": False},
        )
        result = run_full_qa("corrupt.mp4", 15.0, "Hook", "funny", [], [])
        assert result["technical_score"] == 0
        assert result["publish_recommended"] is False

    def test_low_cultural_score_blocks_publish_recommendation_even_with_high_overall(self, mocker):
        # A high comedy/technical score must not paper over a real cultural
        # safety concern — cultural_score has its own independent gate.
        mocker.patch("ffmpeg.probe", return_value=_fake_probe(duration=15.0))
        mocker.patch(
            "app.services.culturetoon_qa.run_ai_judge_qa",
            return_value={
                "comedy_score": 100, "cultural_score": 30,
                "cultural_concerns": ["relies on an accent-mockery stereotype"], "reasoning": "r", "judge_failed": False,
            },
        )
        result = run_full_qa("fake.mp4", 15.0, "Hook", "funny", [], [])
        assert result["cultural_score"] < PUBLISH_CULTURAL_THRESHOLD
        assert result["publish_recommended"] is False
        assert "accent-mockery" in result["issues"][0]

    def test_judge_failure_surfaces_in_issues(self, mocker):
        mocker.patch("ffmpeg.probe", return_value=_fake_probe(duration=15.0))
        mocker.patch(
            "app.services.culturetoon_qa.run_ai_judge_qa",
            return_value={"comedy_score": 50, "cultural_score": 50, "cultural_concerns": [], "reasoning": "placeholder", "judge_failed": True},
        )
        result = run_full_qa("fake.mp4", 15.0, "Hook", "funny", [], [])
        assert any("AI-judge scoring failed" in issue for issue in result["issues"])

    def test_thresholds_are_the_documented_values(self):
        # Locks in the specific numbers so a future change to them is a
        # deliberate, reviewed edit, not an accidental one.
        assert PUBLISH_OVERALL_THRESHOLD == 70
        assert PUBLISH_CULTURAL_THRESHOLD == 60
        assert PUBLISH_TECHNICAL_THRESHOLD == 50

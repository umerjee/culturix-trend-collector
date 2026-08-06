"""Tests for the faceless-reel pipeline (app/services/clip_script.py,
clip_audio.py, clip_image.py, clip_render.py, reel_pipeline.py) and its
wiring into app/media/service.py's "reel" media_type dispatch. Matches this
codebase's established convention: mocked external calls (LLM, edge-tts,
HybridImageProvider, ffmpeg subprocess, storage), functions called directly.
"""
import os
os.environ.setdefault("QWEN_API_KEY", "fake-qwen-key")

import pytest

from app.services.clip_script import generate_script, ScriptGenerationError
from app.services.clip_audio import generate_voiceover_with_timestamps, TTSGenerationError
from app.services.clip_image import generate_segment_images, ImageGenerationError
from app.services.clip_render import render_clip, RenderError
from app.services.reel_pipeline import run_reel_pipeline, ReelGenerationError, _split_words_into_segments


class TestGenerateScript:
    def test_requires_non_empty_idea_text(self):
        with pytest.raises(ScriptGenerationError):
            generate_script("")
        with pytest.raises(ScriptGenerationError):
            generate_script("   ")

    def test_success_grounds_prompt_in_idea_text(self, mocker):
        mock_client = mocker.Mock()
        mock_client.chat.completions.create.return_value = mocker.Mock(
            choices=[mocker.Mock(message=mocker.Mock(content="A punchy hook-first script."))]
        )
        mocker.patch("app.services.clip_script._get_qwen_client", return_value=mock_client)

        result = generate_script("Hook: X\n\nCaption: Y\n\nCTA: Z")

        assert result == "A punchy hook-first script."
        sent_prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Hook: X" in sent_prompt
        assert "Caption: Y" in sent_prompt
        assert "hook-first" in sent_prompt.lower()

    def test_provider_error_wrapped(self, mocker):
        mocker.patch("app.services.clip_script._get_qwen_client", side_effect=RuntimeError("boom"))
        with pytest.raises(ScriptGenerationError):
            generate_script("some idea")


class TestGenerateVoiceoverWithTimestamps:
    def test_requires_non_empty_script(self, tmp_path):
        with pytest.raises(TTSGenerationError):
            generate_voiceover_with_timestamps("", str(tmp_path / "out.mp3"))

    def test_success_writes_audio_and_returns_word_timestamps(self, mocker, tmp_path):
        async def fake_synthesize(text, voice):
            return b"fake-mp3-bytes", [
                {"word": "Hello", "start": 0.1, "end": 0.4},
                {"word": "world", "start": 0.5, "end": 0.9},
            ]
        mocker.patch("app.services.clip_audio._synthesize_with_word_timestamps", side_effect=fake_synthesize)

        out_path = str(tmp_path / "voice.mp3")
        words = generate_voiceover_with_timestamps("Hello world", out_path)

        assert words == [
            {"word": "Hello", "start": 0.1, "end": 0.4},
            {"word": "world", "start": 0.5, "end": 0.9},
        ]
        with open(out_path, "rb") as f:
            assert f.read() == b"fake-mp3-bytes"

    def test_no_word_timestamps_raises(self, mocker, tmp_path):
        async def fake_synthesize(text, voice):
            return b"fake-mp3-bytes", []
        mocker.patch("app.services.clip_audio._synthesize_with_word_timestamps", side_effect=fake_synthesize)

        with pytest.raises(TTSGenerationError, match="no word timestamps"):
            generate_voiceover_with_timestamps("Hello world", str(tmp_path / "voice.mp3"))


class TestGenerateSegmentImages:
    def test_requires_non_empty_segments(self, tmp_path):
        with pytest.raises(ImageGenerationError):
            generate_segment_images([], str(tmp_path))

    def test_success_writes_one_image_per_segment(self, mocker, tmp_path):
        from app.media.base import MediaResult
        mock_provider = mocker.Mock()
        mock_provider.generate.side_effect = [
            MediaResult(asset_bytes=b"img0", content_type="image/png"),
            MediaResult(asset_bytes=b"img1", content_type="image/png"),
        ]
        mocker.patch("app.media.image_hybrid.HybridImageProvider", return_value=mock_provider)

        paths = generate_segment_images(["segment one text", "segment two text"], str(tmp_path))

        assert len(paths) == 2
        with open(paths[0], "rb") as f:
            assert f.read() == b"img0"
        with open(paths[1], "rb") as f:
            assert f.read() == b"img1"
        assert mock_provider.generate.call_count == 2


class TestSplitWordsIntoSegments:
    def test_empty_words_returns_empty(self):
        assert _split_words_into_segments([], 3) == []

    def test_splits_into_expected_number_of_chunks(self):
        words = [{"word": f"w{i}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(9)]
        segments = _split_words_into_segments(words, 3)
        assert len(segments) == 3
        # Each segment's start matches its first word's real start time.
        assert segments[0][1] == 0.0
        assert segments[1][1] == words[3]["start"]
        assert segments[2][1] == words[6]["start"]

    def test_fewer_words_than_segments_yields_fewer_segments(self):
        words = [{"word": "solo", "start": 0.0, "end": 0.3}]
        segments = _split_words_into_segments(words, 3)
        assert len(segments) == 1


class TestRenderClip:
    def test_requires_non_empty_segments(self, tmp_path):
        with pytest.raises(RenderError):
            render_clip([], str(tmp_path / "audio.mp3"), [], str(tmp_path / "out.mp4"))

    def test_success_runs_segment_concat_and_mux_passes(self, mocker, tmp_path):
        mocker.patch("app.services.clip_render._require_ffmpeg")
        mocker.patch("app.services.clip_render._probe_duration", return_value=6.0)

        audio_path = str(tmp_path / "audio.mp3")
        with open(audio_path, "wb") as f:
            f.write(b"fake-audio")
        img_path = str(tmp_path / "img.png")
        with open(img_path, "wb") as f:
            f.write(b"fake-image")
        output_path = str(tmp_path / "out.mp4")

        def fake_run(cmd, **kwargs):
            # The output path is always the last positional arg in every
            # ffmpeg invocation this module makes.
            out = cmd[-1]
            with open(out, "wb") as f:
                f.write(b"fake-video-bytes")
            return mocker.Mock(returncode=0, stderr="")
        mock_run = mocker.patch("app.services.clip_render.subprocess.run", side_effect=fake_run)

        words = [{"word": "hi", "start": 0.0, "end": 0.3}]
        result = render_clip([(img_path, 3.0), (img_path, 3.0)], audio_path, words, output_path)

        assert result["video_path"] == output_path
        assert result["duration_seconds"] == 6.0
        # 2 segment renders + 1 concat + 1 final mux = 4 ffmpeg calls.
        assert mock_run.call_count == 4
        with open(output_path, "rb") as f:
            assert f.read() == b"fake-video-bytes"

    def test_ffmpeg_failure_raises(self, mocker, tmp_path):
        mocker.patch("app.services.clip_render._require_ffmpeg")
        mocker.patch("app.services.clip_render._probe_duration", return_value=6.0)
        mocker.patch("app.services.clip_render.subprocess.run", return_value=mocker.Mock(returncode=1, stderr="exploded"))

        audio_path = str(tmp_path / "audio.mp3")
        with open(audio_path, "wb") as f:
            f.write(b"fake-audio")
        img_path = str(tmp_path / "img.png")
        with open(img_path, "wb") as f:
            f.write(b"fake-image")

        with pytest.raises(RenderError, match="ffmpeg failed"):
            render_clip([(img_path, 3.0)], audio_path, [{"word": "hi", "start": 0.0, "end": 0.3}], str(tmp_path / "out.mp4"))


class TestRunReelPipeline:
    def test_full_pipeline_success(self, mocker, tmp_path):
        mocker.patch("app.services.clip_script.generate_script", return_value="A hook-first spoken script.")
        words = [
            {"word": "A", "start": 0.0, "end": 0.2},
            {"word": "hook-first", "start": 0.3, "end": 0.9},
            {"word": "spoken", "start": 1.0, "end": 1.4},
            {"word": "script.", "start": 1.5, "end": 2.0},
        ]

        def fake_voiceover(script_text, output_path, voice=None):
            with open(output_path, "wb") as f:
                f.write(b"fake-audio-bytes")
            return words
        mocker.patch("app.services.clip_audio.generate_voiceover_with_timestamps", side_effect=fake_voiceover)

        def fake_images(segments, output_dir):
            paths = []
            for i in range(len(segments)):
                p = os.path.join(output_dir, f"img_{i}.png")
                with open(p, "wb") as f:
                    f.write(b"fake-image")
                paths.append(p)
            return paths
        mocker.patch("app.services.clip_image.generate_segment_images", side_effect=fake_images)

        mock_render = mocker.patch(
            "app.services.clip_render.render_clip",
            return_value={"video_path": "unused", "duration_seconds": 2.0},
        )

        # run_reel_pipeline reads the actual rendered file from disk, so the
        # mocked render_clip must still produce a real file at the path it's
        # given (the 4th positional arg).
        def render_side_effect(segments, audio_path, word_timestamps, output_path):
            with open(output_path, "wb") as f:
                f.write(b"final-video-bytes")
            return {"video_path": output_path, "duration_seconds": 2.0}
        mock_render.side_effect = render_side_effect

        result = run_reel_pipeline("Hook\n\nCaption\n\nCTA")

        assert result.asset_bytes == b"final-video-bytes"
        assert result.content_type == "video/mp4"
        assert result.duration_seconds == 2.0

        # Verify segment count matches NUM_IMAGE_SEGMENTS and durations were
        # computed from real word timestamps, not a flat estimate.
        render_call = mock_render.call_args
        segments_arg = render_call[0][0]
        assert len(segments_arg) <= 3
        assert all(duration > 0 for _, duration in segments_arg)

    def test_script_failure_wrapped_as_reel_error(self, mocker):
        mocker.patch(
            "app.services.clip_script.generate_script",
            side_effect=ScriptGenerationError("llm down"),
        )
        with pytest.raises(ReelGenerationError, match="Script generation failed"):
            run_reel_pipeline("some idea")

    def test_voiceover_failure_wrapped_as_reel_error(self, mocker):
        mocker.patch("app.services.clip_script.generate_script", return_value="script text")
        mocker.patch(
            "app.services.clip_audio.generate_voiceover_with_timestamps",
            side_effect=TTSGenerationError("tts down"),
        )
        with pytest.raises(ReelGenerationError, match="Voiceover generation failed"):
            run_reel_pipeline("some idea")


class TestMediaServiceDispatch:
    """Confirms moving the _get_provider() lookup inside each branch
    (required so "reel" doesn't KeyError on a _PROVIDERS lookup that was
    never meant to have a reel entry) didn't break the other 4 media
    types, and that "reel" correctly routes to run_reel_pipeline."""

    def test_reel_routes_to_reel_pipeline(self, mocker):
        from app.media import service
        from app.media.base import MediaResult

        mocker.patch("app.db.SessionLocal")
        mock_pipeline = mocker.patch(
            "app.services.reel_pipeline.run_reel_pipeline",
            return_value=MediaResult(asset_bytes=b"x", content_type="video/mp4", duration_seconds=10.0),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/reel.mp4")
        mocker.patch.object(service, "_update_row")

        service.run_generation(
            row_id="00000000-0000-0000-0000-000000000000", media_type="reel", prompt="idea text",
            user_id="u1", content_id="c1", idea_index=0,
        )

        mock_pipeline.assert_called_once_with("idea text")

    def test_voiceover_still_routes_to_provider(self, mocker):
        from app.media import service
        from app.media.base import MediaResult

        mocker.patch("app.db.SessionLocal")
        mock_provider = mocker.Mock()
        mock_provider.synthesize.return_value = MediaResult(asset_bytes=b"x", content_type="audio/mpeg", duration_seconds=5.0)
        mocker.patch.object(service, "_get_provider", return_value=mock_provider)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/voice.mp3")
        mocker.patch.object(service, "_update_row")

        service.run_generation(
            row_id="00000000-0000-0000-0000-000000000000", media_type="voiceover", prompt="hook text",
            user_id="u1", content_id="c1", idea_index=0,
        )

        mock_provider.synthesize.assert_called_once_with("hook text")

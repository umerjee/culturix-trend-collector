"""One narrator voice for a whole World video: retiming, the mix, and the guarantee
that the voice never comes from the video model."""
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.services import world_narration as wn
from app.services.world_narration import NarrationError, NarrationPlan, ShotLine


def _shots(*texts):
    return [{"shot_number": i + 1, "duration_seconds": 8, "shot_focus": "subject", "subject_visual": "v",
             "dialogue": t} for i, t in enumerate(texts)]


class TestVoice:
    def test_default_english_voice(self, monkeypatch):
        monkeypatch.delenv("WORLD_NARRATOR_VOICE", raising=False)
        assert wn.narrator_voice("en") == "en-GB-RyanNeural"

    def test_english_voice_can_be_overridden(self, monkeypatch):
        monkeypatch.setenv("WORLD_NARRATOR_VOICE", "en-US-GuyNeural")
        assert wn.narrator_voice("en") == "en-US-GuyNeural"
        assert wn.narrator_voice("fr") == wn.NARRATOR_VOICES["fr"]  # override is English-only

    def test_unknown_language_is_an_error_not_a_silent_default(self):
        with pytest.raises(NarrationError):
            wn.narrator_voice("xx")

    def test_every_ui_language_has_a_voice(self):
        for code in ("en", "fr", "es", "de", "it", "pt", "ar", "he", "hi", "ja", "ko", "zh-CN", "tr", "ru"):
            assert wn.narrator_voice(code)


class TestRetime:
    def test_a_shot_is_sized_to_fit_its_line_with_lead_in_and_tail(self):
        shots, starts = wn.retime_shots(_shots("a", "b"), {0: 7.5, 1: 9.5})
        assert [s["duration_seconds"] for s in shots] == [9, 11]   # ceil(7.5+0.25+0.6), ceil(9.5+0.85)
        assert starts == [0.0, 9.0]

    def test_short_lines_get_the_minimum_shot_length(self):
        shots, _ = wn.retime_shots(_shots("hi"), {0: 1.0})
        assert shots[0]["duration_seconds"] == wn.MIN_SHOT_SECONDS

    def test_narrated_shots_are_marked_external_and_others_keep_their_length(self):
        base = _shots("spoken", "")
        base[1]["dialogue"] = None
        shots, starts = wn.retime_shots(base, {0: 5.0})
        assert shots[0]["narration"] == "external" and "narration" not in shots[1]
        assert shots[1]["duration_seconds"] == 8 and starts == [0.0, 6.0]  # ceil(5.0+0.25+0.6)

    def test_input_shots_are_not_mutated(self):
        base = _shots("spoken")
        wn.retime_shots(base, {0: 9.0})
        assert base[0]["duration_seconds"] == 8 and "narration" not in base[0]

    def test_a_line_too_long_for_one_shot_is_rejected_not_rushed(self):
        with pytest.raises(NarrationError) as exc:
            wn.retime_shots(_shots("a very long line"), {0: 14.0})
        assert "too long" in str(exc.value) and "Shot 1" in str(exc.value)


class TestPrepare:
    @pytest.fixture
    def fake(self, mocker):
        calls = []

        def synth(text, voice):
            calls.append((text, voice))
            return f"audio:{text}".encode()

        mocker.patch.object(wn, "probe_duration", side_effect=lambda data, suffix=".mp3": {
            b"audio:one": 6.0, b"audio:two": 8.0, b"audio:three": 7.0}[data])
        return SimpleNamespace(synth=synth, calls=calls)

    def test_every_line_uses_the_same_voice(self, fake):
        plan = wn.prepare_narration(_shots("one", "two", "three"), "en", synth=fake.synth)
        assert {voice for _, voice in fake.calls} == {plan.voice}
        assert len(fake.calls) == 3

    def test_lines_are_positioned_and_shots_retimed(self, fake):
        plan = wn.prepare_narration(_shots("one", "two", "three"), "en", synth=fake.synth)
        assert [round(l.start, 2) for l in plan.lines] == [0.25, 7.25, 16.25]
        assert [s["duration_seconds"] for s in plan.shots] == [7, 9, 8]
        assert plan.total_seconds == 24 and all(s["narration"] == "external" for s in plan.shots)

    def test_an_explicit_voice_wins(self, fake):
        assert wn.prepare_narration(_shots("one"), "en", voice="en-US-GuyNeural", synth=fake.synth).voice == "en-US-GuyNeural"

    def test_no_narration_is_an_error(self, fake):
        with pytest.raises(NarrationError):
            wn.prepare_narration([{"shot_number": 1, "dialogue": None}], "en", synth=fake.synth)

    def test_a_synthesis_failure_propagates_so_the_render_never_starts(self, fake):
        def boom(text, voice):
            raise NarrationError("service down")
        with pytest.raises(NarrationError):
            wn.prepare_narration(_shots("one"), "en", synth=boom)


class TestSynthesize:
    def test_retries_then_succeeds(self, mocker):
        mocker.patch.object(wn.asyncio, "run", side_effect=[RuntimeError("x"), RuntimeError("y"), b"mp3"])
        assert wn.synthesize("hello", "en-GB-RyanNeural") == b"mp3"

    def test_gives_up_with_a_clear_error(self, mocker):
        run = mocker.patch.object(wn.asyncio, "run", side_effect=RuntimeError("down"))
        with pytest.raises(NarrationError) as exc:
            wn.synthesize("hello", "en-GB-RyanNeural")
        assert run.call_count == 3 and "down" in str(exc.value)

    def test_empty_audio_is_a_failure(self, mocker):
        mocker.patch.object(wn.asyncio, "run", return_value=b"")
        with pytest.raises(NarrationError):
            wn.synthesize("hello", "en-GB-RyanNeural")

    def test_emoji_are_not_read_aloud(self, mocker):
        gen = mocker.patch.object(wn, "_generate", return_value=b"x")
        mocker.patch.object(wn.asyncio, "run", side_effect=lambda result: result)  # _generate is mocked, not a coroutine
        wn.synthesize("Fire 🔥 everywhere", "en-GB-RyanNeural")
        assert gen.call_args.args[0] == "Fire everywhere"


class TestScriptView:
    def test_shots_are_replaced_everything_else_is_delegated(self):
        real = SimpleNamespace(shots=["stored"], hook_line="Hook", visual_style="illustrated_history")
        plan = NarrationPlan(voice="v", language="en", lines=[], shots=["retimed"])
        view = plan.render_script(real)
        assert view.shots == ["retimed"] and view.hook_line == "Hook" and view.visual_style == "illustrated_history"
        assert real.shots == ["stored"]  # the stored script is untouched


class TestMuxCommand:
    def test_offsets_ambient_and_copy(self):
        cmd = wn.mux_command("v.mp4", ["a.mp3", "b.mp3"], [250, 9000], "o.mp4", True, 31.3)
        graph = cmd[cmd.index("-filter_complex") + 1]
        assert f"[0:a]volume={wn.AMBIENT_GAIN}[amb]" in graph
        assert "[1:a]adelay=250|250" in graph and "[2:a]adelay=9000|9000" in graph
        assert "amix=inputs=3" in graph and "normalize=0" in graph
        assert cmd[cmd.index("-c:v") + 1] == "copy" and cmd[cmd.index("-t") + 1] == "31.300"

    def test_no_ambient_track_means_narration_only(self):
        graph = wn.mux_command("v.mp4", ["a.mp3"], [0], "o.mp4", False, 5)[wn.mux_command("v.mp4", ["a.mp3"], [0], "o.mp4", False, 5).index("-filter_complex") + 1]
        assert "[0:a]" not in graph and "amix=inputs=1" in graph


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")
class TestRealMux:
    @staticmethod
    def _make(tmp_path, args, name):
        out = tmp_path / name
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, str(out)], check=True)
        return out.read_bytes()

    def test_narration_is_mixed_over_the_video_and_the_video_stream_is_untouched(self, tmp_path):
        video = self._make(tmp_path, ["-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=6",
                                      "-f", "lavfi", "-i", "sine=frequency=200:duration=6", "-shortest",
                                      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"], "v.mp4")
        tone = self._make(tmp_path, ["-f", "lavfi", "-i", "sine=frequency=600:duration=2"], "n.mp3")
        plan = NarrationPlan(voice="v", language="en", shots=[], total_seconds=6.0,
                             lines=[ShotLine(shot_index=0, text="t", audio=tone, duration=2.0, start=1.0)])
        out = plan.mux(video)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
                                "-of", "csv=p=0", "-i", "-"], input=out, capture_output=True).stdout.decode()
        assert "video" in probe and "audio" in probe and "h264" in probe
        assert 5.5 < wn.probe_duration(out, ".mp4") < 6.5

    def test_offsets_are_scaled_when_the_real_video_is_shorter_than_planned(self, tmp_path, mocker):
        video = self._make(tmp_path, ["-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=4",
                                      "-c:v", "libx264", "-pix_fmt", "yuv420p"], "v.mp4")   # no audio track
        tone = self._make(tmp_path, ["-f", "lavfi", "-i", "sine=frequency=600:duration=1"], "n.mp3")
        spy = mocker.spy(wn, "mux_command")
        plan = NarrationPlan(voice="v", language="en", shots=[], total_seconds=8.0,
                             lines=[ShotLine(shot_index=0, text="t", audio=tone, duration=1.0, start=4.0)])
        plan.mux(video)
        offsets = spy.call_args.args[2]
        assert offsets == [2000]   # 4.0s planned * (4s actual / 8s planned)
        assert spy.call_args.args[4] is False   # no ambient track to keep

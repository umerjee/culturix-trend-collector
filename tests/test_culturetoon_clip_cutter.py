"""Tests for app/services/culturetoon_clip_cutter.py. Matches this
codebase's convention (see test_clip_generation.py) of not requiring a real
ffmpeg binary in the test suite — the offset math is tested directly (pure
function, no subprocess), and cut_clips()'s ffmpeg invocation is mocked.
"""
import os

import pytest

from app.services.culturetoon_clip_cutter import (
    cut_clips,
    _compute_offsets,
    ClipCutError,
)


class TestComputeOffsets:
    def test_single_clip_when_num_clips_is_one(self):
        assert _compute_offsets(30.0, num_clips=1, clip_seconds=6) == [0.0]

    def test_evenly_spaced_across_duration(self):
        offsets = _compute_offsets(30.0, num_clips=4, clip_seconds=6)
        assert len(offsets) == 4
        assert offsets[0] == 0.0
        assert offsets[-1] == pytest.approx(24.0)  # last clip still fits: 24 + 6 = 30
        assert offsets == sorted(offsets)

    def test_short_source_collapses_to_one_clip(self):
        # Source shorter than the target clip length — nothing to space out.
        assert _compute_offsets(4.0, num_clips=4, clip_seconds=6) == [0.0]

    def test_zero_duration_raises(self):
        with pytest.raises(ClipCutError, match="Invalid source video duration"):
            _compute_offsets(0.0, num_clips=4, clip_seconds=6)

    def test_offsets_never_exceed_max_start(self):
        offsets = _compute_offsets(20.0, num_clips=4, clip_seconds=6)
        assert all(o <= 14.0 for o in offsets)  # 20 - 6 = 14


class TestCutClips:
    def test_happy_path(self, mocker, tmp_path):
        mocker.patch("app.services.culturetoon_clip_cutter._require_ffmpeg")
        mocker.patch("app.services.culturetoon_clip_cutter._probe_duration", return_value=24.0)

        def _fake_run(cmd, **kwargs):
            out_path = cmd[-1]
            with open(out_path, "wb") as f:
                f.write(b"fake-mp4-bytes")
            result = mocker.Mock()
            result.returncode = 0
            return result

        mocker.patch("subprocess.run", side_effect=_fake_run)

        results = cut_clips(str(tmp_path / "source.mp4"), str(tmp_path), num_clips=4, clip_seconds=6)
        assert len(results) == 4
        for r in results:
            assert os.path.exists(r["path"])
            assert r["end"] > r["start"]

    def test_ffmpeg_failure_raises(self, mocker, tmp_path):
        mocker.patch("app.services.culturetoon_clip_cutter._require_ffmpeg")
        mocker.patch("app.services.culturetoon_clip_cutter._probe_duration", return_value=24.0)

        fail_result = mocker.Mock()
        fail_result.returncode = 1
        fail_result.stderr = "ffmpeg exploded"
        mocker.patch("subprocess.run", return_value=fail_result)

        with pytest.raises(ClipCutError, match="ffmpeg failed"):
            cut_clips(str(tmp_path / "source.mp4"), str(tmp_path))

    def test_missing_ffmpeg_binary_raises(self, mocker, tmp_path):
        mocker.patch("shutil.which", return_value=None)
        with pytest.raises(ClipCutError, match="ffmpeg/ffprobe not found"):
            cut_clips(str(tmp_path / "source.mp4"), str(tmp_path))

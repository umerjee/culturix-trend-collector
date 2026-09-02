"""Tests for app/services/culturetoon_reaper.py — cleaning up toons whose
generation process died without ever updating their status."""
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QWEN_API_KEY", "")

from app.services.culturetoon_reaper import (
    reap_stale_animating_toons,
    STALE_AFTER_SECONDS,
)


class _Query:
    """Minimal stand-in for the SQLAlchemy query chain used by the reaper."""

    def __init__(self, rows):
        self._rows = rows
        self.filters = []

    def filter(self, *args):
        self.filters.extend(args)
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self._rows = rows
        self.committed = False

    def query(self, _model):
        return _Query(self._rows)

    def commit(self):
        self.committed = True


def _toon(mocker, hours_old, status="animating", video=None):
    t = mocker.Mock()
    t.status = status
    t.generation_error = None
    t.final_video_url = video
    t.updated_at = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    return t


class TestReapStaleAnimatingToons:
    def test_marks_a_long_stuck_toon_as_failed(self, mocker):
        """Confirmed live: two toons stuck at 23.9h and 45.8h, each showing
        "Generating…" forever."""
        stuck = _toon(mocker, hours_old=24)
        session = _Session([stuck])
        assert reap_stale_animating_toons(session) == 1
        assert stuck.status == "failed"
        assert "interrupted" in stuck.generation_error
        assert session.committed

    def test_explains_the_cause_and_that_a_retry_is_safe(self, mocker):
        stuck = _toon(mocker, hours_old=24)
        reap_stale_animating_toons(_Session([stuck]))
        assert "restarted" in stuck.generation_error
        assert "Generate again" in stuck.generation_error

    def test_never_promotes_a_stale_toon_to_ready(self, mocker):
        """A stuck toon often still carries the URL of a PREVIOUS successful
        take. Calling that "ready" would report an interrupted generation as
        a finished one."""
        stuck = _toon(mocker, hours_old=24, video="https://example.com/old-take.mp4")
        reap_stale_animating_toons(_Session([stuck]))
        assert stuck.status == "failed"
        # The earlier video stays viewable; only the status stops lying.
        assert stuck.final_video_url == "https://example.com/old-take.mp4"

    def test_commits_nothing_when_there_is_nothing_stale(self, mocker):
        session = _Session([])
        assert reap_stale_animating_toons(session) == 0
        assert not session.committed

    def test_cutoff_is_beyond_the_longest_legitimate_render(self):
        """A render can now legitimately run close to an hour (MAX_TOTAL_
        SECONDS at ~18.3 GPU seconds per output second, 3600s job timeouts).
        Reaping a LIVE generation is far worse than a stale spinner."""
        assert STALE_AFTER_SECONDS >= 2 * 3600

import importlib.util
import sys
from pathlib import Path

import pytest

# Not a package module (it's a top-level script meant to be run directly,
# see its own docstring) — load it by path instead of a normal import.
_MODULE_PATH = Path(__file__).resolve().parent.parent / "run_scheduled_ingest.py"
_spec = importlib.util.spec_from_file_location("run_scheduled_ingest", _MODULE_PATH)
run_scheduled_ingest = importlib.util.module_from_spec(_spec)
sys.modules["run_scheduled_ingest"] = run_scheduled_ingest
_spec.loader.exec_module(run_scheduled_ingest)


class TestRegisterJobs:
    def test_nothing_enabled_registers_no_jobs(self, monkeypatch, mocker):
        monkeypatch.delenv("SCHEDULE_APIFY", raising=False)
        monkeypatch.delenv("SCHEDULE_SCRAPECREATORS", raising=False)
        scheduler = mocker.Mock()
        assert run_scheduled_ingest.register_jobs(scheduler) == 0
        scheduler.add_job.assert_not_called()

    def test_apify_only(self, monkeypatch, mocker):
        monkeypatch.setenv("SCHEDULE_APIFY", "true")
        monkeypatch.delenv("SCHEDULE_SCRAPECREATORS", raising=False)
        scheduler = mocker.Mock()
        assert run_scheduled_ingest.register_jobs(scheduler) == 1
        assert scheduler.add_job.call_count == 1
        assert scheduler.add_job.call_args.kwargs["id"] == "apify_ingest"

    def test_both_enabled(self, monkeypatch, mocker):
        monkeypatch.setenv("SCHEDULE_APIFY", "true")
        monkeypatch.setenv("SCHEDULE_SCRAPECREATORS", "true")
        scheduler = mocker.Mock()
        assert run_scheduled_ingest.register_jobs(scheduler) == 2

    def test_case_insensitive_true_value(self, monkeypatch, mocker):
        monkeypatch.setenv("SCHEDULE_APIFY", "True")
        monkeypatch.delenv("SCHEDULE_SCRAPECREATORS", raising=False)
        scheduler = mocker.Mock()
        assert run_scheduled_ingest.register_jobs(scheduler) == 1

    def test_anything_other_than_true_is_disabled(self, monkeypatch, mocker):
        monkeypatch.setenv("SCHEDULE_APIFY", "yes")  # not "true"
        monkeypatch.delenv("SCHEDULE_SCRAPECREATORS", raising=False)
        scheduler = mocker.Mock()
        assert run_scheduled_ingest.register_jobs(scheduler) == 0

"""World production: plan -> grounded script -> fact-check -> draft."""
import uuid
from types import SimpleNamespace

import pytest

from app.services import world_production as wp

LONG_FACTS = "Carcassonne is a fortified French city. " * 20  # well above the thin-source threshold


def _item(raw_text=LONG_FACTS, summary="A fortified city.", region=None, category="archaeology", source_type="unesco"):
    return SimpleNamespace(
        id=uuid.uuid4(), title="Carcassonne", summary=summary, raw_text=raw_text, region=region,
        category=category, source_type=source_type, source_url="https://whc.unesco.org/en/list/345",
    )


def _script(total=30):
    return {"hook_line": "H", "shots": [{"shot_number": 1, "duration_seconds": total, "dialogue": "Narration."}],
            "total_duration_seconds": total}


@pytest.fixture
def llm(mocker):
    base = "app.services.culturetoon_script."
    return SimpleNamespace(
        duration=mocker.patch(base + "suggest_world_duration",
                              return_value={"duration_seconds": 45, "beat_count": 4, "rationale": "Several beats."}),
        write=mocker.patch(base + "generate_world_script", return_value=_script()),
        grounding=mocker.patch(base + "judge_world_grounding",
                               return_value={"grounded": True, "unsupported_claims": [], "judge_failed": False}),
        craft=mocker.patch(base + "judge_script_comedy", return_value={"comedy_score": 70}),
        host=mocker.patch(base + "select_thematic_host"),
    )


class TestSourceFacts:
    def test_summary_comes_first_then_raw_text(self):
        facts = wp.build_source_facts(_item(raw_text="RAW", summary="SUM"))
        assert facts.index("SUM") < facts.index("RAW")

    def test_identical_summary_and_raw_not_duplicated(self):
        assert wp.build_source_facts(_item(raw_text="SAME", summary="SAME")).count("SAME") == 1

    def test_source_label(self):
        assert wp.source_label(_item(source_type="unesco")) == "UNESCO World Heritage"
        assert wp.source_label(_item(source_type="wikipedia")) == "Wikipedia"


class TestPlan:
    def test_returns_suggestion_options_and_cost_estimates(self, llm):
        plan = wp.plan_world_video(_item())
        assert plan["duration_seconds"] == 45 and plan["beat_count"] == 4
        assert plan["allowed_durations"] == [15, 20, 30, 45, 60]
        assert set(plan["estimate"]) == {"15", "20", "30", "45", "60"}
        assert plan["estimate"]["60"]["cost_usd"] > plan["estimate"]["15"]["cost_usd"]
        assert plan["thin_source"] is False

    def test_thin_source_is_capped_not_padded(self, llm):
        plan = wp.plan_world_video(_item(raw_text="Short.", summary="Tiny."))
        assert plan["thin_source"] is True
        assert plan["duration_seconds"] == wp.THIN_SOURCE_MAX_SECONDS
        assert plan["beat_count"] <= 3
        assert "capped" in plan["rationale"]

    def test_short_suggestion_on_thin_source_is_left_alone(self, llm):
        llm.duration.return_value = {"duration_seconds": 15, "beat_count": 1, "rationale": "One reveal."}
        plan = wp.plan_world_video(_item(raw_text="Short.", summary="Tiny."))
        assert plan["duration_seconds"] == 15 and plan["rationale"] == "One reveal."


class TestGenerateDraft:
    def test_source_facts_and_region_name_reach_the_writer(self, llm):
        wp.generate_world_draft(None, _item(region=None), duration_seconds=30, beat_count=3, persist=False)
        kwargs = llm.write.call_args.kwargs
        assert kwargs["source_facts"] == wp.build_source_facts(_item())
        assert kwargs["source_label"] == "UNESCO World Heritage"
        assert kwargs["target_duration_seconds"] == 30 and kwargs["num_shots"] == 3

    def test_no_host_by_default(self, llm):
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.host.call_count == 0 and llm.write.call_args.kwargs["host_variant"] is None
        assert result["host"] is False

    def test_host_only_when_opted_in(self, llm):
        llm.host.return_value = SimpleNamespace(id=uuid.uuid4())
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, use_host=True, persist=False)
        assert llm.host.call_count == 1 and result["host"] is True

    def test_a_people_visual_without_the_flag_is_rewritten_once_with_the_problems(self, llm, mocker):
        bad = {"hook_line": "H", "total_duration_seconds": 30, "shots": [
            {"shot_number": 1, "shot_focus": "subject", "subject_visual": "Soldiers advancing", "dialogue": "x"}]}
        good = {"hook_line": "H", "total_duration_seconds": 30, "shots": [
            {"shot_number": 1, "shot_focus": "subject", "subject_visual": "Small figures on a wide beach",
             "people": "distant", "dialogue": "x"}]}
        llm.write.side_effect = [bad, good]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.write.call_count == 2
        assert "Shot 1" in llm.write.call_args.kwargs["visual_fixes"][0]
        assert "visual_warnings" not in result["judgment"]

    def test_still_broken_after_the_rewrite_is_forced_to_distant_and_warned(self, llm):
        bad = {"hook_line": "H", "total_duration_seconds": 30, "shots": [
            {"shot_number": 1, "shot_focus": "subject", "subject_visual": "Soldiers advancing", "dialogue": "x"}]}
        llm.write.side_effect = [bad, bad]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.write.call_count == 2
        assert result["judgment"]["visual_warnings"] and "set to distant" in result["judgment"]["visual_warnings"][0]

    def test_consistent_visuals_are_not_rewritten(self, llm):
        ok = {"hook_line": "H", "total_duration_seconds": 30, "shots": [
            {"shot_number": 1, "shot_focus": "subject", "subject_visual": "An empty beach", "dialogue": "x"}]}
        llm.write.side_effect = [ok]
        wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.write.call_count == 1

    def test_grounded_draft_is_written_once(self, llm):
        wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.write.call_count == 1

    def test_unsupported_claims_trigger_one_revision_that_avoids_them(self, llm):
        llm.grounding.side_effect = [
            {"grounded": False, "unsupported_claims": ["Built in 1066", "12 towers"], "judge_failed": False},
            {"grounded": True, "unsupported_claims": [], "judge_failed": False},
        ]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.write.call_count == 2
        assert llm.write.call_args.kwargs["avoid_claims"] == ["Built in 1066", "12 towers"]
        assert result["grounding"]["grounded"] is True

    def test_worse_revision_is_discarded(self, llm):
        first, second = _script(30), _script(20)
        llm.write.side_effect = [first, second]
        llm.grounding.side_effect = [
            {"grounded": False, "unsupported_claims": ["a"], "judge_failed": False},
            {"grounded": False, "unsupported_claims": ["a", "b"], "judge_failed": False},
        ]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert result["duration_seconds"] == 30  # kept the first draft, which had fewer unsupported claims
        assert result["grounding"]["unsupported_claims"] == ["a"]

    def test_judgment_carries_grounding_and_plan(self, llm):
        result = wp.generate_world_draft(None, _item(), duration_seconds=45, beat_count=4, persist=False)
        assert result["judgment"]["grounding"]["grounded"] is True
        assert result["judgment"]["duration_plan"] == {"duration_seconds": 45, "beat_count": 4}

    def test_uses_the_suggested_duration_when_none_given(self, llm):
        wp.generate_world_draft(None, _item(), persist=False)
        assert llm.write.call_args.kwargs["target_duration_seconds"] == 45

    def test_overridden_duration_derives_its_own_beat_count_without_an_llm_plan(self, llm):
        wp.generate_world_draft(None, _item(), duration_seconds=60, persist=False)
        assert llm.write.call_args.kwargs["num_shots"] == wp.BEATS_FOR_DURATION[60]
        assert llm.duration.call_count == 0

    def test_every_allowed_duration_has_beats_at_most_12s_per_shot(self):
        assert set(wp.BEATS_FOR_DURATION) == set(wp.ALLOWED_DURATIONS)
        for duration, beats in wp.BEATS_FOR_DURATION.items():
            assert duration / beats <= 12

    def test_rejects_a_duration_outside_the_allowed_set(self, llm):
        with pytest.raises(wp.WorldDraftError):
            wp.generate_world_draft(None, _item(), duration_seconds=33, beat_count=3, persist=False)

    def test_duplicate_live_draft_is_refused(self, llm, mocker):
        mocker.patch.object(wp, "find_live_draft", return_value=object())
        with pytest.raises(wp.WorldDraftExists):
            wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3)


class TestRegionName:
    def test_known_unknown_and_missing(self):
        from app.collectors.region_codes import region_name
        assert region_name("fr") == "France"
        assert region_name("ZZ") == "ZZ"
        assert region_name(None) == "the world"


class TestSourceUrlBackfill:
    def test_derives_only_what_is_certain(self):
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "backfill", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "backfill_curated_source_urls.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.derive_source_url("unesco", "345:Restoration of Carcassonne") == "https://whc.unesco.org/en/list/345"
        assert mod.derive_source_url("unesco", "not-numeric:x") is None
        assert mod.derive_source_url("wikipedia", "History of Italy:Roman Empire") == "https://en.wikipedia.org/wiki/History_of_Italy"
        assert mod.derive_source_url("wikipedia", "Carcassonne:Sieges") is None
        assert mod.derive_source_url("trend", "1") is None

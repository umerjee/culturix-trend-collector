"""World production: plan -> grounded script -> fact-check -> draft."""
import uuid
from datetime import datetime
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


def _review(score=80, passes=True, suggestions=None):
    return {"score": score, "comedy_score": score, "passes_bar": passes, "feedback": "ok", "judge_failed": False,
            "dimensions": {"hook": {"score": score, "weight": 20, "note": ""}}, "suggestions": suggestions or [],
            "review_version": 1}


@pytest.fixture
def llm(mocker):
    base = "app.services.culturetoon_script."
    return SimpleNamespace(
        duration=mocker.patch(base + "suggest_world_duration",
                              return_value={"duration_seconds": 45, "beat_count": 4, "rationale": "Several beats."}),
        write=mocker.patch(base + "generate_world_script", return_value=_script()),
        grounding=mocker.patch(base + "judge_world_grounding",
                               return_value={"grounded": True, "unsupported_claims": [], "judge_failed": False}),
        review=mocker.patch("app.services.world_review.review_world_script", return_value=_review()),
        era=mocker.patch("app.services.world_era.determine_world_era", return_value=None),
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
            {"shot_number": 1, "shot_focus": "subject", "camera_movement": "tracking",
             "subject_visual": "Small figures run across a wide beach as smoke rolls past",
             "people": "distant", "dialogue": "x"}]}
        llm.write.side_effect = [bad, good]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.write.call_count == 2
        assert "Shot 1" in llm.write.call_args.kwargs["visual_fixes"][0]
        assert "visual_warnings" not in result["judgment"]

    def test_still_broken_after_the_rewrite_is_forced_to_distant_and_warned(self, llm):
        bad = {"hook_line": "H", "total_duration_seconds": 30, "shots": [
            {"shot_number": 1, "shot_focus": "subject", "subject_visual": "Soldiers advancing", "dialogue": "x"}]}
        llm.write.side_effect = [bad, bad, bad]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.write.call_count == 1 + wp.MAX_VISUAL_REWRITES
        assert result["judgment"]["visual_warnings"] and "set to distant" in result["judgment"]["visual_warnings"][0]

    def test_consistent_visuals_are_not_rewritten(self, llm):
        ok = {"hook_line": "H", "total_duration_seconds": 30, "shots": [
            {"shot_number": 1, "shot_focus": "subject", "camera_movement": "dolly",
             "subject_visual": "Waves surge up an empty beach as smoke rolls across the sand", "dialogue": "x"}]}
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


class TestVisualStyle:
    def test_plan_lists_the_available_styles(self, llm):
        plan = wp.plan_world_video(_item())
        keys = [style["key"] for style in plan["visual_styles"]]
        assert "illustrated_history" in keys and "graphic_novel" in keys
        assert all(style["label"] for style in plan["visual_styles"])

    def test_the_style_is_reported_on_the_draft(self, llm):
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False,
                                         visual_style="illustrated_history")
        assert result["visual_style"] == "illustrated_history"

    def test_no_style_is_the_default_photoreal_look(self, llm):
        assert wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)["visual_style"] is None

    def test_an_unknown_style_is_rejected_before_anything_is_written(self, llm):
        with pytest.raises(wp.WorldDraftError) as exc:
            wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False, visual_style="watercolour")
        assert "visual_style" in str(exc.value)
        llm.write.assert_not_called()

    def test_every_style_has_a_label_and_a_scene_prompt(self):
        for key, style in wp.WORLD_VISUAL_STYLES.items():
            assert style["label"] and len(style["prompt"]) > 40, key


class TestMotionRewrite:
    STILL = {"hook_line": "H", "total_duration_seconds": 30, "shots": [
        {"shot_number": 1, "shot_focus": "subject", "subject_visual": "A wide view of a quiet beach",
         "camera_movement": "static", "people": "none", "dialogue": "x"}]}
    MOVING = {"hook_line": "H", "total_duration_seconds": 30, "shots": [
        {"shot_number": 1, "shot_focus": "subject", "camera_movement": "tracking", "people": "none",
         "subject_visual": "Waves surge over steel obstacles while smoke rolls across an empty beach", "dialogue": "x"}]}

    def test_a_still_script_is_rewritten_once_with_the_motion_problems(self, llm):
        llm.write.side_effect = [self.STILL, self.MOVING]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.write.call_count == 2
        fixes = llm.write.call_args.kwargs["visual_fixes"]
        assert any("still scene" in f for f in fixes) and any("camera_movement is static" in f for f in fixes)
        assert "visual_warnings" not in result["judgment"]

    def test_still_after_the_rewrite_is_surfaced_as_a_warning(self, llm):
        llm.write.side_effect = [self.STILL] * (1 + wp.MAX_VISUAL_REWRITES)
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        warnings = result["judgment"]["visual_warnings"]
        assert any("still scene" in w for w in warnings)

    def test_a_moving_script_is_written_once(self, llm):
        llm.write.side_effect = [self.MOVING]
        wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.write.call_count == 1


class TestArchivedListing:
    """Retired drafts keep their rendered video, and the admin page links every take."""

    @pytest.fixture
    def session(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db import Base
        from app.models.curated_item import CuratedItem
        from app.models.toon import Toon
        from app.models.toon_script import ToonScript
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine, tables=[Toon.__table__, ToonScript.__table__, CuratedItem.__table__])
        s = sessionmaker(bind=engine)()
        yield s
        s.close()

    @staticmethod
    def _add(session, title, status, video=None, style=None, world=True):
        from app.models.toon import Toon
        from app.models.toon_script import ToonScript
        script = ToonScript(brand_id=uuid.uuid4(), hook_line="H", shots=[{"dialogue": "x"}], total_duration_seconds=30,
                            visual_style=style, generation_source="ai", status="approved", is_world_content=world)
        session.add(script)
        session.commit()
        toon = Toon(brand_id=uuid.uuid4(), script_id=script.id, title=title, status=status, final_video_url=video,
                    raw_video_url=video, is_world_content=world, subject_region="FR")
        session.add(toon)
        session.commit()
        return toon

    def test_archived_list_has_only_retired_drafts_that_still_have_a_video(self, session):
        from app.main import _world_production_rows
        self._add(session, "retired with video", "archived", video="https://cdn/a.mp4", style="illustrated_history")
        self._add(session, "retired never rendered", "archived", video=None)
        self._add(session, "live draft", "ready", video="https://cdn/b.mp4")
        self._add(session, "not a world video", "archived", video="https://cdn/c.mp4", world=False)
        rows = _world_production_rows(session, archived=True, limit=50)
        assert [r["title"] for r in rows] == ["retired with video"]
        assert rows[0]["final_video_url"] == "https://cdn/a.mp4" and rows[0]["visual_style"] == "illustrated_history"

    def test_working_list_excludes_archived_and_reports_the_style(self, session):
        from app.main import _world_production_rows
        self._add(session, "retired", "archived", video="https://cdn/a.mp4")
        self._add(session, "live", "idea", style="graphic_novel")
        rows = _world_production_rows(session, archived=False, limit=50)
        assert [r["title"] for r in rows] == ["live"] and rows[0]["visual_style"] == "graphic_novel"

    def test_previous_takes_default_to_an_empty_list_not_null(self, session):
        from app.main import _world_production_rows
        self._add(session, "live", "ready", video="https://cdn/b.mp4")
        assert _world_production_rows(session, archived=False, limit=50)[0]["previous_video_urls"] == []

    def test_newest_first(self, session):
        from app.main import _world_production_rows
        first = self._add(session, "older", "archived", video="https://cdn/1.mp4")
        second = self._add(session, "newer", "archived", video="https://cdn/2.mp4")
        first.created_at = datetime(2026, 1, 1)
        second.created_at = datetime(2026, 2, 1)
        session.commit()
        assert [r["title"] for r in _world_production_rows(session, archived=True, limit=50)] == ["newer", "older"]


class TestScenes:
    """Each shot opens on its own reference photo: one shot per scene, in order."""

    SCENES = [
        {"brief": "The Allied armada crosses the Channel", "image_url": "https://s/1.jpg", "credit": "IWM", "name": "Armada"},
        {"brief": "A battleship fires a broadside", "image_url": "https://s/2.jpg", "credit": "US Navy", "name": "Bombardment"},
        {"brief": "Landing craft approach the beach", "image_url": None},
    ]

    @staticmethod
    def _script(n):
        return {"hook_line": "H", "total_duration_seconds": 30, "shots": [
            {"shot_number": i + 1, "shot_focus": "subject", "camera_movement": "tracking", "people": "none",
             "subject_visual": "Waves surge and smoke rolls past the ships", "dialogue": "x"} for i in range(n)]}

    def test_scene_briefs_reach_the_writer_and_set_the_shot_count(self, llm):
        llm.write.side_effect = [self._script(3)]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=9, scenes=self.SCENES, persist=False)
        kwargs = llm.write.call_args.kwargs
        assert kwargs["num_shots"] == 3          # forced to the number of scenes, whatever was asked
        assert kwargs["scene_briefs"] == ["The Allied armada crosses the Channel", "A battleship fires a broadside",
                                          "Landing craft approach the beach"]
        assert result["scenes"] == 3

    def test_the_wrong_shot_count_is_rewritten_once_with_a_clear_instruction(self, llm):
        llm.write.side_effect = [self._script(2), self._script(3)]
        wp.generate_world_draft(None, _item(), duration_seconds=30, scenes=self.SCENES, persist=False)
        assert llm.write.call_count == 2
        assert any("exactly 3 shots" in fix for fix in llm.write.call_args.kwargs["visual_fixes"])

    def test_references_and_credits_are_recorded_on_the_judgment(self, llm):
        llm.write.side_effect = [self._script(3)]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, scenes=self.SCENES, persist=False)
        refs = result["judgment"]["references"]
        assert [r["scene"] for r in refs] == [0, 1, 2] and refs[1]["credit"] == "US Navy" and refs[2]["url"] is None

    def test_no_scenes_leaves_the_old_behaviour_untouched(self, llm):
        wp.generate_world_draft(None, _item(), duration_seconds=30, beat_count=3, persist=False)
        assert llm.write.call_args.kwargs["scene_briefs"] is None

    @pytest.mark.parametrize("scenes", [[], [{"brief": ""}], [{"brief": "  "}], [{"brief": "x"}] * 9, [{"image_url": "u"}]])
    def test_invalid_scene_lists_are_rejected_before_any_generation(self, llm, scenes):
        with pytest.raises(wp.WorldDraftError):
            wp.generate_world_draft(None, _item(), duration_seconds=30, scenes=scenes, persist=False)
        llm.write.assert_not_called()

    def test_persisting_creates_a_location_per_photo_and_maps_each_shot_to_its_scene(self, llm, mocker):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db import Base
        from app.models.character_brand import CharacterBrand
        from app.models.toon import Toon
        from app.models.toon_background import ToonBackground
        from app.models.toon_script import ToonScript
        from app.models.trend import Trend
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine, tables=[CharacterBrand.__table__, Toon.__table__, ToonScript.__table__,
                                                       ToonBackground.__table__, Trend.__table__])
        db = sessionmaker(bind=engine)()
        db.add(CharacterBrand(user_id=uuid.uuid4(), name="World"))
        db.commit()
        llm.write.side_effect = [self._script(3)]
        item = _item(region="FR")

        result = wp.generate_world_draft(db, item, duration_seconds=30, scenes=self.SCENES, visual_style="illustrated_history")

        script = db.query(ToonScript).filter_by(id=uuid.UUID(result["script_id"])).one()
        assert [s["scene_index"] for s in script.shots] == [0, 1, 2]
        backgrounds = db.query(ToonBackground).order_by(ToonBackground.name).all()
        assert sorted(b.image_url for b in backgrounds) == ["https://s/1.jpg", "https://s/2.jpg"]   # scene 3 has no photo
        assert {b.country for b in backgrounds} == {"France"}
        mapped = {e["scene_index"]: e["background_id"] for e in script.scene_backgrounds}
        assert sorted(mapped) == [0, 1] and set(mapped.values()) == {str(b.id) for b in backgrounds}
        assert script.visual_style == "illustrated_history"
        assert script.comedy_judgment["references"][0]["credit"] == "IWM"

    def test_photo_scenes_get_the_reference_people_mode_and_photoless_ones_keep_distant(self, llm):
        script = {"hook_line": "H", "total_duration_seconds": 30, "shots": [
            {"shot_number": i + 1, "shot_focus": "subject", "camera_movement": "tracking", "people": "distant",
             "subject_visual": "Soldiers run up the beach as smoke rolls past", "dialogue": "x"} for i in range(3)]}
        llm.write.side_effect = [script]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, scenes=self.SCENES, persist=False)
        assert [s["people"] for s in result["shots"]] == ["reference", "reference", "distant"]   # scene 3 has no photo

    def test_a_none_shot_stays_none_even_with_a_photo(self, llm):
        script = {"hook_line": "H", "total_duration_seconds": 30, "shots": [
            {"shot_number": i + 1, "shot_focus": "subject", "camera_movement": "tracking", "people": "none",
             "subject_visual": "A battleship fires and smoke rolls across the sea", "dialogue": "x"} for i in range(3)]}
        llm.write.side_effect = [script]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, scenes=self.SCENES, persist=False)
        assert {s["people"] for s in result["shots"]} == {"none"}


SUGGESTION = {"shot": 1, "dimension": "hook", "issue": "The opener is a label.", "fix": "Open on the odds."}


class TestAutoImprove:
    """A draft that misses the bar is rewritten once with the reviewer's suggestions; the better one is kept."""

    def _reviews(self, llm, *reviews):
        llm.review.side_effect = list(reviews)

    def test_a_passing_draft_is_not_rewritten(self, llm):
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert llm.write.call_count == 1 and llm.review.call_count == 1
        assert "auto_improved" not in result["judgment"]

    def test_a_failing_draft_is_rewritten_with_its_suggestions_and_the_better_one_wins(self, llm):
        first, second = _script(), {**_script(), "hook_line": "Better hook"}
        llm.write.side_effect = [first, second]
        self._reviews(llm, _review(55, False, [SUGGESTION]), _review(82, True))
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert result["hook_line"] == "Better hook"
        assert result["judgment"]["auto_improved"] is True and result["judgment"]["first_score"] == 55
        revision_call = llm.write.call_args_list[1].kwargs
        assert revision_call["previous_draft"]["hook_line"] == "H"
        assert revision_call["improvements"] == ["Shot 1: The opener is a label. Fix: Open on the odds."]

    def test_a_rewrite_that_scores_lower_is_discarded(self, llm):
        llm.write.side_effect = [_script(), {**_script(), "hook_line": "Worse"}]
        self._reviews(llm, _review(60, False, [SUGGESTION]), _review(40, False))
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert result["hook_line"] == "H" and result["judgment"]["score"] == 60
        assert "auto_improved" not in result["judgment"]

    def test_a_rewrite_that_adds_unsupported_claims_is_discarded_even_if_it_scores_higher(self, llm):
        llm.write.side_effect = [_script(), {**_script(), "hook_line": "Invented"}, {**_script(), "hook_line": "Invented"}]
        clean = {"grounded": True, "unsupported_claims": [], "judge_failed": False}
        dirty = {"grounded": False, "unsupported_claims": ["a fact"], "judge_failed": False}
        llm.grounding.side_effect = [clean, dirty, dirty]
        self._reviews(llm, _review(60, False, [SUGGESTION]), _review(90, True))
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert result["hook_line"] == "H"

    def test_no_suggestions_means_nothing_to_apply(self, llm):
        self._reviews(llm, _review(50, False, []))
        wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert llm.write.call_count == 1

    def test_a_failed_review_does_not_trigger_a_rewrite(self, llm):
        llm.review.return_value = {**_review(0, None), "score": None, "passes_bar": None, "judge_failed": True}
        wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert llm.write.call_count == 1


class TestImproveAndPreview:
    @pytest.fixture(autouse=True)
    def _no_era_model_call(self, mocker):
        mocker.patch("app.services.world_era.determine_world_era", return_value=None)

    @pytest.fixture
    def db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db import Base
        from app.models.curated_item import CuratedItem
        from app.models.toon import Toon
        from app.models.toon_background import ToonBackground
        from app.models.toon_script import ToonScript
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine, tables=[Toon.__table__, ToonScript.__table__, CuratedItem.__table__,
                                                      ToonBackground.__table__])
        s = sessionmaker(bind=engine)()
        yield s
        s.close()

    @staticmethod
    def _draft(db, status="idea", judgment=None, with_photos=False):
        from app.models.curated_item import CuratedItem
        from app.models.toon import Toon
        from app.models.toon_background import ToonBackground
        from app.models.toon_script import ToonScript
        item = CuratedItem(source_type="wikipedia", source_ref="Neptune", title="Operation Neptune", summary="The landing.",
                           raw_text="Facts " * 100, category="history", region=None)
        db.add(item)
        db.commit()
        shots = [{"shot_number": i + 1, "duration_seconds": 8, "shot_focus": "subject", "camera_movement": "tracking",
                  "people": "none", "dialogue": f"Line {i + 1} is spoken here.",
                  "subject_visual": "Ships surge and smoke rolls", "scene_index": i if with_photos else None} for i in range(2)]
        scene_backgrounds = None
        if with_photos:
            scene_backgrounds = []
            for i in range(2):
                bg = ToonBackground(brand_id=uuid.uuid4(), name=f"Scene {i}", image_url=f"https://cdn/{i}.jpg",
                                    description=f"Brief {i}")
                db.add(bg)
                db.commit()
                scene_backgrounds.append({"scene_index": i, "background_id": str(bg.id)})
        script = ToonScript(brand_id=uuid.uuid4(), hook_line="H", shots=shots, total_duration_seconds=16,
                            generation_source="ai", status="approved", is_world_content=True,
                            comedy_judgment=judgment, scene_backgrounds=scene_backgrounds)
        db.add(script)
        db.commit()
        toon = Toon(brand_id=script.brand_id, script_id=script.id, title="Operation Neptune", status=status,
                    is_world_content=True, curated_item_id=item.id)
        db.add(toon)
        db.commit()
        return toon, script

    def test_a_rendered_draft_cannot_be_improved_or_rescored(self, db, llm):
        toon, _ = self._draft(db, status="ready")
        with pytest.raises(wp.WorldDraftError, match="before its video is rendered"):
            wp.improve_world_draft(db, toon)
        with pytest.raises(wp.WorldDraftError):
            wp.review_world_draft(db, toon)

    def test_review_scores_an_old_draft_and_keeps_its_other_judgment_fields(self, db, llm):
        toon, script = self._draft(db, judgment={"comedy_score": 50, "grounding": {"grounded": True, "unsupported_claims": []},
                                                 "references": [{"scene": 0}]})
        llm.review.return_value = _review(72, False, [SUGGESTION])
        wp.review_world_draft(db, toon)
        db.refresh(script)
        assert script.comedy_judgment["score"] == 72 and script.comedy_judgment["suggestions"] == [SUGGESTION]
        assert script.comedy_judgment["references"] == [{"scene": 0}]
        llm.grounding.assert_not_called()       # the stored fact-check is reused, not repeated

    def test_improve_applies_the_suggestions_and_the_curators_note_then_saves_the_better_script(self, db, llm):
        toon, script = self._draft(db, judgment={**_review(60, False, [SUGGESTION]),
                                                 "grounding": {"grounded": True, "unsupported_claims": []},
                                                 "duration_plan": {"duration_seconds": 15, "beat_count": 2}})
        better = {"hook_line": "New hook", "total_duration_seconds": 16, "shots": [
            {"shot_number": 1, "duration_seconds": 8, "shot_focus": "subject", "people": "none", "dialogue": "a", "subject_visual": "x"},
            {"shot_number": 2, "duration_seconds": 8, "shot_focus": "subject", "people": "none", "dialogue": "b", "subject_visual": "y"}]}
        llm.write.return_value = better
        llm.review.return_value = _review(84, True)
        outcome = wp.improve_world_draft(db, toon, note="make the ending bigger")
        assert outcome == {"improved": True, "score_before": 60, "score_after": 84, "message": "Script improved."}
        db.refresh(script)
        assert script.hook_line == "New hook" and script.comedy_judgment["score"] == 84
        assert script.comedy_judgment["first_score"] == 60
        kwargs = llm.write.call_args.kwargs
        assert kwargs["previous_draft"]["hook_line"] == "H"
        assert kwargs["improvements"][-1] == "The curator specifically asked: make the ending bigger"
        assert kwargs["target_duration_seconds"] == 15

    def test_improve_keeps_the_current_script_when_the_rewrite_is_not_better(self, db, llm):
        toon, script = self._draft(db, judgment={**_review(70, False, [SUGGESTION]),
                                                 "grounding": {"grounded": True, "unsupported_claims": []}})
        llm.write.return_value = {**_script(), "hook_line": "Worse"}
        llm.review.return_value = _review(50, False)
        outcome = wp.improve_world_draft(db, toon)
        assert outcome["improved"] is False and "kept" in outcome["message"]
        db.refresh(script)
        assert script.hook_line == "H"

    def test_improve_scores_a_draft_that_has_no_review_yet_before_improving(self, db, llm):
        toon, script = self._draft(db, judgment={"comedy_score": 50, "grounding": {"grounded": True, "unsupported_claims": []}})
        llm.review.side_effect = [_review(60, False, [SUGGESTION]), _review(85, True)]
        llm.write.return_value = {**_script(), "hook_line": "Improved"}
        assert wp.improve_world_draft(db, toon)["improved"] is True
        assert llm.review.call_count == 2

    def test_improve_with_nothing_to_apply_says_so_instead_of_rewriting(self, db, llm):
        toon, _ = self._draft(db, judgment={**_review(90, True, []), "grounding": {"grounded": True, "unsupported_claims": []}})
        outcome = wp.improve_world_draft(db, toon)
        assert outcome["improved"] is False and "no suggestions" in outcome["message"]
        llm.write.assert_not_called()

    def test_improve_keeps_one_shot_per_scene_and_each_shots_photo(self, db, llm):
        toon, script = self._draft(db, with_photos=True, judgment={
            **_review(60, False, [SUGGESTION]), "grounding": {"grounded": True, "unsupported_claims": []},
            "references": [{"scene": 0, "url": "https://cdn/0.jpg"}, {"scene": 1, "url": "https://cdn/1.jpg"}]})
        llm.write.return_value = {"hook_line": "N", "total_duration_seconds": 16, "shots": [
            {"shot_number": i + 1, "duration_seconds": 8, "shot_focus": "subject", "people": "distant",
             "dialogue": "x", "subject_visual": "y"} for i in range(2)]}
        llm.review.return_value = _review(80, True)
        wp.improve_world_draft(db, toon)
        db.refresh(script)
        assert [s["scene_index"] for s in script.shots] == [0, 1]
        assert [s["people"] for s in script.shots] == ["reference", "reference"]     # each opens on a real photo
        assert llm.write.call_args.kwargs["scene_briefs"] == ["Brief 0", "Brief 1"]
        assert script.comedy_judgment["references"][0]["url"] == "https://cdn/0.jpg"   # carried over

    def test_preview_returns_the_narration_plan_and_the_exact_prompts(self, db, mocker):
        from app.services import world_narration as wn
        toon, script = self._draft(db, with_photos=True)
        retimed = [dict(s, duration_seconds=9, narration="external") for s in script.shots]
        plan = wn.NarrationPlan(voice="en-GB-RyanNeural", language="en", shots=retimed, total_seconds=18.0, lines=[
            wn.ShotLine(shot_index=0, text="Line 1 is spoken here.", audio=b"", duration=2.4, start=0.25),
            wn.ShotLine(shot_index=1, text="Line 2 is spoken here.", audio=b"", duration=2.5, start=9.25)])
        mocker.patch.object(wn, "prepare_narration_cached", return_value=plan)
        preview = wp.preview_world_render(db, toon)
        assert preview["duration_seconds"] == 18 and preview["look"] == "Photoreal (default)"
        assert preview["narration"]["voice"] == "en-GB-RyanNeural" and preview["narration"]["error"] is None
        assert preview["narration"]["lines"][1] == {"shot": 2, "text": "Line 2 is spoken here.", "starts_at": 9.2, "speech_seconds": 2.5}
        assert preview["narration"]["shot_seconds"] == [9, 9]
        first = preview["segments"][0]
        assert first["mode"] == "subject_only" and first["opening_frame"] == {
            "kind": "reference_photo", "url": "https://cdn/0.jpg", "name": "Scene 0"}
        assert first["image_strength"] == 0.5 and "Ships surge and smoke rolls" in first["prompt"]
        assert "ambient sound only" in first["prompt"]           # the model is not asked to speak the line
        assert "watermark" in first["negative_prompt"] and preview["estimate"]["cost_usd"] > 0

    def test_preview_reports_a_narration_failure_before_any_gpu_is_spent(self, db, mocker):
        from app.services import world_narration as wn
        toon, _ = self._draft(db)
        mocker.patch.object(wn, "prepare_narration_cached", side_effect=wn.NarrationError("line too long"))
        preview = wp.preview_world_render(db, toon)
        assert "before using the GPU" in preview["narration"]["error"] and "line too long" in preview["narration"]["error"]
        assert preview["segments"]          # still shows what would be sent


class TestWorldProductionEndpoints:
    """The admin endpoints, called as plain functions (this suite's convention) against an in-memory DB."""

    @pytest.fixture
    def db(self, mocker):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db import Base
        from app.models.curated_item import CuratedItem
        from app.models.toon import Toon
        from app.models.toon_background import ToonBackground
        from app.models.toon_script import ToonScript
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine, tables=[Toon.__table__, ToonScript.__table__, CuratedItem.__table__,
                                                      ToonBackground.__table__])
        s = sessionmaker(bind=engine)()
        mocker.patch("app.db.SessionLocal", return_value=s)
        # Postgres accepts the endpoint's string id; SQLite's UUID type needs a UUID object.
        import app.main as main
        real_lookup = main._world_toon_or_404
        mocker.patch.object(main, "_world_toon_or_404", lambda session, toon_id: real_lookup(session, uuid.UUID(toon_id)))
        yield s
        s.close()

    _draft = staticmethod(TestImproveAndPreview._draft)

    def test_rows_expose_the_review_for_a_scored_draft_and_none_for_an_old_one(self, db):
        from app.main import _world_production_rows
        self._draft(db, judgment={**_review(77, False, [SUGGESTION]), "grounding": {"grounded": True, "unsupported_claims": []}})
        self._draft(db, judgment={"comedy_score": 50})
        by_score = {r["craft_score"]: r for r in _world_production_rows(db, archived=False, limit=10)}
        assert by_score[77]["review"]["suggestions"] == [SUGGESTION] and by_score[77]["review"]["passes_bar"] is False
        assert "grounding" not in by_score[77]["review"]
        assert by_score[50]["review"] is None

    def test_review_endpoint_scores_and_reports_the_score(self, db, llm):
        from app.main import review_world_production_script
        toon, _ = self._draft(db, judgment={"grounding": {"grounded": True, "unsupported_claims": []}})
        llm.review.return_value = _review(73, False, [SUGGESTION])
        tid = str(toon.id)
        assert review_world_production_script(tid) == {"status": "reviewed", "toon_id": tid, "score": 73}

    def test_improve_endpoint_passes_the_note_and_returns_the_outcome(self, db, llm):
        from app.main import improve_world_production_script
        toon, _ = self._draft(db, judgment={**_review(60, False, [SUGGESTION]), "grounding": {"grounded": True, "unsupported_claims": []}})
        llm.write.return_value = {**_script(), "hook_line": "Better"}
        llm.review.return_value = _review(85, True)
        tid = str(toon.id)
        out = improve_world_production_script(tid, {"note": "bigger ending"})
        assert out["improved"] is True and out["score_after"] == 85 and out["toon_id"] == tid
        assert llm.write.call_args.kwargs["improvements"][-1].endswith("bigger ending")

    def test_improve_and_review_are_refused_once_a_video_exists(self, db, llm):
        from fastapi import HTTPException
        from app.main import improve_world_production_script, review_world_production_script
        toon, _ = self._draft(db, status="ready")
        for call in (lambda: improve_world_production_script(str(toon.id), None), lambda: review_world_production_script(str(toon.id))):
            with pytest.raises(HTTPException) as err:
                call()
            assert err.value.status_code == 409 and "before its video is rendered" in err.value.detail

    def test_unknown_draft_is_a_404(self, db):
        from fastapi import HTTPException
        from app.main import improve_world_production_script, preview_world_production_video
        for call in (lambda: improve_world_production_script(str(uuid.uuid4()), None),
                     lambda: preview_world_production_video(str(uuid.uuid4()))):
            with pytest.raises(HTTPException) as err:
                call()
            assert err.value.status_code == 404

    def test_video_prompt_endpoint_returns_the_preview(self, db, mocker):
        from app.main import preview_world_production_video
        from app.services import world_narration as wn
        toon, script = self._draft(db)
        plan = wn.NarrationPlan(voice="v", language="en", lines=[], total_seconds=16.0,
                                shots=[dict(s, duration_seconds=8, narration="external") for s in script.shots])
        mocker.patch.object(wn, "prepare_narration_cached", return_value=plan)
        tid = str(toon.id)
        out = preview_world_production_video(tid)
        assert out["toon_id"] == tid and out["segments"] and out["narration"]["voice"] == "v"


ROME_ERA = {"label": "Ancient Rome, 753 BC to 27 BC", "start_year": -753, "end_year": -27}


def _rome_shots(visual="Villagers run past thatched huts as smoke drifts and water splashes", n=1):
    return {"hook_line": "H", "total_duration_seconds": 30, "shots": [
        {"shot_number": i + 1, "shot_focus": "subject", "camera_movement": "tracking", "people": "none",
         "subject_visual": visual, "dialogue": "Rome grew from a village."} for i in range(n)]}


class TestUnderProduction:
    """The draft row exists from the moment Generate is clicked, so it can be shown greyed while the script
    is written, and a failed script shows its reason instead of vanishing."""

    @pytest.fixture
    def db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db import Base
        from app.models.character_brand import CharacterBrand
        from app.models.curated_item import CuratedItem
        from app.models.toon import Toon
        from app.models.toon_background import ToonBackground
        from app.models.toon_script import ToonScript
        from app.models.trend import Trend
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine, tables=[CharacterBrand.__table__, Toon.__table__, ToonScript.__table__,
                                                       ToonBackground.__table__, Trend.__table__, CuratedItem.__table__])
        s = sessionmaker(bind=engine)()
        s.add(CharacterBrand(user_id=uuid.uuid4(), name="World"))
        s.commit()
        yield s
        s.close()

    @staticmethod
    def _toons(db):
        from app.models.toon import Toon
        return db.query(Toon).all()

    def test_the_draft_exists_and_says_scripting_while_the_script_is_being_written(self, db, llm):
        seen = {}

        def write(**kwargs):
            toons = self._toons(db)
            seen["statuses"] = [t.status for t in toons]
            seen["title"] = toons[0].title if toons else None
            return _script()
        llm.write.side_effect = write
        wp.generate_world_draft(db, _item(), duration_seconds=30)
        assert seen == {"statuses": ["scripting"], "title": "Carcassonne"}

    def test_it_becomes_an_idea_with_the_script_filled_in_and_no_second_row(self, db, llm):
        from app.models.toon_script import ToonScript
        result = wp.generate_world_draft(db, _item(), duration_seconds=30)
        (toon,) = self._toons(db)
        assert toon.status == "idea" and str(toon.id) == result["toon_id"]
        (script,) = db.query(ToonScript).all()
        assert script.status == "approved" and script.hook_line == "H" and script.shots and str(script.id) == result["script_id"]

    def test_a_failed_script_shows_its_reason_and_can_be_generated_again(self, db, llm):
        item = _item()
        llm.write.side_effect = RuntimeError("model overloaded")
        with pytest.raises(RuntimeError):
            wp.generate_world_draft(db, item, duration_seconds=30)
        (toon,) = self._toons(db)
        assert toon.status == "failed" and "model overloaded" in toon.generation_error
        assert wp.find_live_draft(db, item.id) is None            # a failed script does not block a retry
        llm.write.side_effect = None
        wp.generate_world_draft(db, item, duration_seconds=30)
        assert sorted(t.status for t in self._toons(db)) == ["failed", "idea"]

    def test_a_second_click_while_scripting_is_refused(self, db, llm):
        item = _item()
        from app.models.toon import Toon
        wp._start_placeholder(db, item, 30, None)
        with pytest.raises(wp.WorldDraftExists):
            wp.generate_world_draft(db, item, duration_seconds=30)
        assert db.query(Toon).count() == 1

    def test_a_scripting_draft_left_over_from_a_restart_no_longer_blocks(self, db, llm):
        from datetime import datetime, timedelta
        item = _item()
        toon, _ = wp._start_placeholder(db, item, 30, None)
        toon.created_at = datetime.utcnow() - timedelta(minutes=wp.SCRIPTING_STALE_MINUTES + 5)
        db.commit()
        assert wp.scripting_is_stale(toon) is True and wp.find_live_draft(db, item.id) is None
        wp.generate_world_draft(db, item, duration_seconds=30)

    def test_a_dry_run_creates_nothing(self, db, llm):
        wp.generate_world_draft(db, _item(), duration_seconds=30, persist=False)
        assert self._toons(db) == []

    def test_a_draft_archived_while_it_was_being_written_stays_archived(self, db, llm):
        def write(**kwargs):
            for t in self._toons(db):
                t.status = "archived"
            db.commit()
            return _script()
        llm.write.side_effect = write
        wp.generate_world_draft(db, _item(), duration_seconds=30)
        assert [t.status for t in self._toons(db)] == ["archived"]

    def test_the_list_shows_a_scripting_draft_and_reports_a_stale_one_as_failed(self, db):
        from datetime import datetime, timedelta
        from app.main import _world_production_rows
        fresh, _ = wp._start_placeholder(db, _item(), 30, None)
        stale, _ = wp._start_placeholder(db, _item(), 30, None)
        stale.created_at = datetime.utcnow() - timedelta(minutes=wp.SCRIPTING_STALE_MINUTES + 1)
        db.commit()
        rows = {r["id"]: r for r in _world_production_rows(db, archived=False, limit=10)}
        assert rows[str(fresh.id)]["status"] == "scripting" and rows[str(fresh.id)]["shot_count"] == 0
        assert rows[str(stale.id)]["status"] == "failed" and "interrupted" in rows[str(stale.id)]["generation_error"]

    def test_a_draft_without_a_script_cannot_be_rendered_reviewed_or_archived_while_writing(self, db, llm, mocker):
        from fastapi import HTTPException
        import app.main as main
        mocker.patch("app.db.SessionLocal", return_value=db)
        real = main._world_toon_or_404
        mocker.patch.object(main, "_world_toon_or_404", lambda s, tid: real(s, uuid.UUID(tid)))
        toon, _ = wp._start_placeholder(db, _item(), 30, None)
        tid = str(toon.id)
        for call in (lambda: main.generate_world_production_video(tid, mocker.Mock()),
                     lambda: main.archive_world_production(tid)):
            with pytest.raises(HTTPException) as err:
                call()
            assert err.value.status_code == 409 and "still being written" in err.value.detail
        with pytest.raises(wp.WorldDraftError, match="still being written"):
            wp.review_world_draft(db, db.query(type(toon)).filter_by(id=uuid.UUID(tid)).one())


class TestEraInProduction:
    def test_the_era_is_decided_once_and_given_to_the_writer_the_checker_and_the_reviewer(self, llm):
        llm.era.return_value = ROME_ERA
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert llm.era.call_count == 1
        assert llm.write.call_args.kwargs["era"] == ROME_ERA
        assert llm.review.call_args.args[-1] == ROME_ERA
        assert result["judgment"]["era"] == ROME_ERA

    def test_the_curators_period_wins_and_skips_the_model(self, llm):
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False, era_text="Roman Republic, 307 BC")
        llm.era.assert_not_called()
        assert result["judgment"]["era"]["label"] == "Roman Republic, 307 BC" and result["judgment"]["era"]["end_year"] == -307

    def test_a_period_with_no_year_is_refused_before_any_writing(self, llm):
        with pytest.raises(wp.WorldDraftError, match="at least one year"):
            wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False, era_text="a long time ago")
        llm.write.assert_not_called()

    def test_a_modern_object_in_an_ancient_script_triggers_the_rewrite_with_the_problem(self, llm):
        llm.era.return_value = ROME_ERA
        llm.write.side_effect = [_rome_shots("A jeep drives past the huts as smoke drifts and villagers run"),
                                 _rome_shots("Villagers run past thatched huts as smoke drifts and water splashes")]
        wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert llm.write.call_count == 2
        fixes = llm.write.call_args_list[1].kwargs["visual_fixes"]
        assert any("'jeep'" in f and "Ancient Rome" in f for f in fixes)

    def test_the_same_modern_object_is_fine_in_a_modern_period(self, llm):
        llm.era.return_value = {"label": "Normandy, June 1944", "start_year": 1944, "end_year": 1944}
        llm.write.side_effect = [_rome_shots("A jeep drives past the huts as smoke drifts and villagers run")]
        wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert llm.write.call_count == 1

    def test_narration_that_names_a_later_year_widens_the_era(self, llm):
        llm.era.return_value = {"label": "Ancient Rome", "start_year": -753, "end_year": -509}
        shots = _rome_shots()
        shots["shots"][0]["dialogue"] = "In 27 BC the empire began."
        llm.write.side_effect = [shots]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert result["judgment"]["era"]["end_year"] == -27

    def test_an_unknown_era_turns_the_guard_off_rather_than_guessing(self, llm):
        llm.era.return_value = None
        llm.write.side_effect = [_rome_shots("A jeep drives past the huts as smoke drifts and villagers run")]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert llm.write.call_count == 1 and result["judgment"]["era"] is None

    def test_the_stored_era_survives_an_improvement(self, llm):
        llm.era.return_value = ROME_ERA
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        composed = wp._build_judgment({"review": _review(), "grounding": {"grounded": True, "unsupported_claims": []},
                                       "visual_warnings": [], "era": ROME_ERA}, 30, 4, None,
                                      previous_judgment=result["judgment"])
        assert composed["era"] == ROME_ERA


class TestCostEstimate:
    def test_it_uses_the_measured_serverless_rate_not_the_old_placeholder(self):
        from app.services.culturetoon_usage import RENDER_GPU_SECONDS_PER_OUTPUT_SECOND, RUNPOD_SERVERLESS_COST_PER_SECOND
        est = wp.estimate_render(41)
        assert est["cost_usd"] == round(float(RENDER_GPU_SECONDS_PER_OUTPUT_SECOND) * 41 * float(RUNPOD_SERVERLESS_COST_PER_SECOND), 2)
        assert 0.7 <= est["cost_usd"] <= 1.2      # recorded 41s renders cost $0.55 to $1.05; it used to say $0.10


class TestLegacyDraftsGetAnEraBeforeTheyRender:
    """A draft written before periods existed has none, and a prompt with no era gets the model's default:
    the present day (jeeps in ancient Rome). The preview and the render decide and save one first."""

    @pytest.fixture
    def parts(self, mocker):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db import Base
        from app.models.curated_item import CuratedItem
        from app.models.toon import Toon
        from app.models.toon_background import ToonBackground
        from app.models.toon_script import ToonScript
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine, tables=[Toon.__table__, ToonScript.__table__, CuratedItem.__table__,
                                                      ToonBackground.__table__])
        db = sessionmaker(bind=engine)()
        decide = mocker.patch("app.services.world_era.determine_world_era", return_value=ROME_ERA)
        return db, decide

    @staticmethod
    def _draft(db, judgment=None, with_item=True):
        from app.models.curated_item import CuratedItem
        from app.models.toon import Toon
        from app.models.toon_script import ToonScript
        item = CuratedItem(source_type="wikipedia", source_ref="Rome", title="Rise of the Roman Empire", summary="Rome.",
                           raw_text="Facts " * 50, category="history", region=None)
        db.add(item)
        db.commit()
        shots = [{"shot_number": 1, "duration_seconds": 8, "shot_focus": "subject", "camera_movement": "tracking",
                  "people": "none", "dialogue": "In 27 BC the empire began.", "subject_visual": "Legions march and banners snap"}]
        script = ToonScript(brand_id=uuid.uuid4(), hook_line="H", shots=shots, total_duration_seconds=8, generation_source="ai",
                            status="approved", is_world_content=True, comedy_judgment=judgment)
        db.add(script)
        db.commit()
        toon = Toon(brand_id=script.brand_id, script_id=script.id, title="Rise of the Roman Empire", status="idea",
                    is_world_content=True, curated_item_id=item.id if with_item else None)
        db.add(toon)
        db.commit()
        return toon, script

    def test_the_era_is_worked_out_saved_and_widened_to_the_narration(self, parts):
        db, decide = parts
        toon, script = self._draft(db)
        decide.return_value = {"label": "Ancient Rome", "start_year": -753, "end_year": -509}
        era = wp.ensure_script_era(db, toon, script)
        assert era["end_year"] == -27                                    # the narration says "in 27 BC"
        db.refresh(script)
        assert script.comedy_judgment["era"] == era

    def test_a_stored_era_is_used_without_asking_the_model_again(self, parts):
        db, decide = parts
        toon, script = self._draft(db, judgment={"era": ROME_ERA, "score": 70})
        assert wp.ensure_script_era(db, toon, script) == ROME_ERA
        decide.assert_not_called()

    def test_existing_judgment_fields_are_kept(self, parts):
        db, _ = parts
        toon, script = self._draft(db, judgment={"score": 70, "suggestions": []})
        wp.ensure_script_era(db, toon, script)
        db.refresh(script)
        assert script.comedy_judgment["score"] == 70 and script.comedy_judgment["era"]

    def test_no_subject_or_no_answer_or_an_error_means_no_era_and_never_an_exception(self, parts):
        db, decide = parts
        toon, script = self._draft(db, with_item=False)
        assert wp.ensure_script_era(db, toon, script) is None
        toon2, script2 = self._draft(db)
        decide.return_value = None
        assert wp.ensure_script_era(db, toon2, script2) is None
        decide.side_effect = RuntimeError("model down")
        assert wp.ensure_script_era(db, toon2, script2) is None

    def test_the_preview_of_a_legacy_draft_opens_every_segment_with_the_era(self, parts, mocker):
        from app.services import world_narration as wn
        db, _ = parts
        toon, script = self._draft(db)
        plan = wn.NarrationPlan(voice="v", language="en", lines=[], total_seconds=8.0,
                                shots=[dict(s, duration_seconds=8, narration="external") for s in script.shots])
        mocker.patch.object(wn, "prepare_narration_cached", return_value=plan)
        preview = wp.preview_world_render(db, toon)
        assert preview["segments"][0]["prompt"].startswith("Ancient Rome, 753 BC to 27 BC. Set in the ancient world")
        assert "jeeps" in preview["segments"][0]["negative_prompt"]


class TestBoundedVisualRewrites:
    GOOD = _rome_shots("Legionaries run across a stone bridge as banners snap and dust billows")
    MAP = _rome_shots("A map of the Mediterranean shows the empire's territories")

    def test_a_second_rewrite_fixes_what_the_first_did_not(self, llm):
        llm.write.side_effect = [self.MAP, self.MAP, self.GOOD]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert llm.write.call_count == 3
        assert "map" not in result["shots"][0]["subject_visual"] and "visual_warnings" not in result["judgment"]

    def test_it_stops_as_soon_as_the_rules_are_met(self, llm):
        llm.write.side_effect = [self.MAP, self.GOOD]
        wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert llm.write.call_count == 2

    def test_it_never_runs_more_than_the_cap(self, llm):
        llm.write.side_effect = [self.MAP] * 10
        wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert llm.write.call_count == 1 + wp.MAX_VISUAL_REWRITES

    def test_a_worse_rewrite_is_not_used_and_stops_the_loop(self, llm):
        worse = _rome_shots("An infographic of the trade routes appears on screen", n=2)   # two bad shots against one
        llm.write.side_effect = [self.MAP, worse, self.GOOD]
        result = wp.generate_world_draft(None, _item(), duration_seconds=30, persist=False)
        assert "map of the Mediterranean" in result["shots"][0]["subject_visual"]     # kept the better of the two
        assert llm.write.call_count == 2

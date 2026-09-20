"""Editorial review of World scripts: measurable signals, weighted score, pass rules, fail-open."""
import pytest

from app.services import world_review as wr
from app.services.culturetoon_script import ToonScriptGenerationError


def _shot(n=1, visual="Landing craft plough through surf as smoke rolls across the beach", camera="tracking",
          shot_type="wide", dialogue="Eight thousand ships crossed the Channel in the dark, and the coast did not know.", **kw):
    return {"shot_number": n, "shot_focus": "subject", "subject_visual": visual, "camera_movement": camera,
            "shot_type": shot_type, "dialogue": dialogue, **kw}


STILL = "A calm beach under a grey sky with a distant horizon"


class TestSignals:
    def test_action_with_varied_cameras_scores_high(self):
        shots = [_shot(1, camera="tracking", shot_type="wide"),
                 _shot(2, visual="A battleship fires a broadside and smoke billows over the sea", camera="dolly", shot_type="low_angle"),
                 _shot(3, visual="Troops wade ashore and run up the beach between steel obstacles", camera="crane", shot_type="aerial")]
        assert wr.dynamism_signals(shots) >= 85

    def test_still_scenes_with_a_static_camera_score_low(self):
        shots = [_shot(i, visual=STILL, camera="static", shot_type="wide") for i in (1, 2, 3)]
        assert wr.dynamism_signals(shots) <= 25

    def test_a_moving_camera_alone_does_not_make_a_still_scene_dynamic(self):
        assert wr.dynamism_signals([_shot(1, visual=STILL, camera="tracking")]) < 60

    def test_no_subject_shots_is_none(self):
        assert wr.dynamism_signals([]) is None
        assert wr.dynamism_signals([{"shot_focus": "character"}]) is None

    def test_narration_signal_is_the_share_of_speakable_lines(self):
        ok = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
        assert wr.narration_signals([_shot(dialogue=ok), _shot(dialogue="too short"), _shot(dialogue=ok), _shot(dialogue=ok + " " + ok)]) == 50
        assert wr.narration_signals([_shot(dialogue="")]) is None

    def test_accuracy_signal_drops_per_unsupported_claim_and_ignores_an_unrun_check(self):
        assert wr.accuracy_signal({"grounded": True, "unsupported_claims": []}) == 100
        assert wr.accuracy_signal({"grounded": False, "unsupported_claims": ["a", "b"]}) == 40
        assert wr.accuracy_signal({"grounded": False, "unsupported_claims": list("abcdef")}) == 0
        assert wr.accuracy_signal({"grounded": None, "unsupported_claims": []}) is None
        assert wr.accuracy_signal(None) is None


def _llm(scores, suggestions=None, summary="Solid but safe."):
    return {"dimensions": {k: {"score": v, "note": f"{k} note"} for k, v in scores.items()},
            "suggestions": suggestions or [], "summary": summary}


GOOD = {"hook": 90, "story": 90, "dynamism": 90, "narration": 90, "visuals": 90}
CLEAN = {"grounded": True, "unsupported_claims": [], "judge_failed": False}


@pytest.fixture
def script():
    return {"hook_line": "H", "shots": [_shot(1), _shot(2, camera="dolly", shot_type="low_angle"),
                                         _shot(3, camera="crane", shot_type="aerial")]}


def _review(mocker, script, payload=None, grounding=CLEAN, error=None):
    call = mocker.patch("app.services.world_review._call_llm_json", return_value=payload, side_effect=error)
    return wr.review_world_script(script, "Operation Neptune", 41, "facts", grounding), call


class TestReview:
    def test_weighted_score_and_pass(self, mocker, script):
        review, _ = _review(mocker, script, _llm(GOOD))
        assert review["score"] == review["comedy_score"] and review["score"] >= 85
        assert review["passes_bar"] is True and review["judge_failed"] is False
        assert set(review["dimensions"]) == set(wr.DIMENSIONS)
        assert sum(d["weight"] for d in review["dimensions"].values()) == 100

    def test_the_score_is_a_weighted_average_not_the_models_overall(self, mocker, script):
        review, _ = _review(mocker, script, _llm({**GOOD, "hook": 0}))
        assert review["dimensions"]["hook"]["score"] == 0
        assert 60 <= review["score"] <= 80          # hook is 20% of the total
        assert review["passes_bar"] is False        # a dimension under the floor blocks the pass

    def test_a_dynamism_the_model_praises_is_pulled_down_by_a_still_script(self, mocker):
        still = {"hook_line": "H", "shots": [_shot(i, visual=STILL, camera="static") for i in (1, 2, 3)]}
        review, _ = _review(mocker, still, _llm(GOOD))
        assert review["dimensions"]["dynamism"]["score"] <= 60      # 50/50 with the measured ~20
        assert review["passes_bar"] is False

    def test_unsupported_claims_lower_accuracy_and_block_a_pass(self, mocker, script):
        review, _ = _review(mocker, script, _llm(GOOD), grounding={"grounded": False, "unsupported_claims": ["x"]})
        assert review["dimensions"]["accuracy"]["score"] == 70
        assert review["passes_bar"] is False

    def test_an_unrun_fact_check_is_left_out_rather_than_counted_as_zero(self, mocker, script):
        review, _ = _review(mocker, script, _llm(GOOD), grounding={"grounded": None, "unsupported_claims": [], "judge_failed": True})
        assert review["dimensions"]["accuracy"]["score"] is None
        assert review["score"] >= 85

    def test_scores_are_clamped_and_junk_ignored(self, mocker, script):
        payload = _llm({**GOOD, "hook": 250, "story": "n/a"})
        payload["dimensions"]["bogus"] = {"score": 5}
        review, _ = _review(mocker, script, payload)
        assert review["dimensions"]["hook"]["score"] == 100
        assert review["dimensions"]["story"]["score"] is None
        assert "bogus" not in review["dimensions"]

    def test_suggestions_are_cleaned_and_capped(self, mocker, script):
        raw = [{"shot": 2, "dimension": "Dynamism", "issue": "Still frame.", "fix": "Have the ramp drop."},
               {"shot": None, "dimension": "nonsense", "issue": "Flat opener", "fix": "Open on the odds"},
               {"issue": "no fix"}, "not a dict", {"issue": "", "fix": "x"}] + \
              [{"shot": i, "issue": f"i{i}", "fix": f"f{i}"} for i in range(10)]
        review, _ = _review(mocker, script, _llm(GOOD, suggestions=raw))
        suggestions = review["suggestions"]
        assert len(suggestions) == wr.MAX_SUGGESTIONS
        assert suggestions[0] == {"shot": 2, "dimension": "dynamism", "issue": "Still frame.", "fix": "Have the ramp drop."}
        assert suggestions[1]["dimension"] is None and suggestions[1]["shot"] is None

    def test_feedback_leads_with_the_summary_and_the_first_fix(self, mocker, script):
        review, _ = _review(mocker, script, _llm(GOOD, suggestions=[{"shot": 1, "issue": "Weak opener.", "fix": "x"}], summary="Decent."))
        assert review["feedback"] == "Decent. Fix first: Weak opener."

    def test_fails_open_with_only_the_measurable_dimensions(self, mocker, script):
        review, _ = _review(mocker, script, error=ToonScriptGenerationError("llm down"))
        assert review["judge_failed"] is True and review["score"] is None and review["passes_bar"] is None
        assert review["dimensions"]["hook"]["score"] is None
        assert review["dimensions"]["dynamism"]["score"] is not None
        assert review["suggestions"] == []

    def test_the_prompt_shows_the_reviewer_the_picture_not_only_the_words(self, mocker, script):
        _, call = _review(mocker, script, _llm(GOOD))
        prompt = call.call_args.args[0]
        assert "NARRATION:" in prompt and "VISUAL: Landing craft plough" in prompt and "camera: tracking" in prompt
        assert "Operation Neptune" in prompt and "41s" in prompt


class TestNotesAndView:
    def test_improvement_notes_name_the_shot_and_carry_the_curators_note(self):
        review = {"suggestions": [{"shot": 3, "issue": "Static.", "fix": "Ramp drops."},
                                  {"shot": None, "issue": "Flat arc.", "fix": "Escalate."}]}
        notes = wr.improvement_notes(review, "  make the ending bigger ")
        assert notes == ["Shot 3: Static. Fix: Ramp drops.", "Whole video: Flat arc. Fix: Escalate.",
                         "The curator specifically asked: make the ending bigger"]

    def test_no_suggestions_and_no_note_is_empty(self):
        assert wr.improvement_notes({"suggestions": []}, "   ") == []

    def test_review_view_is_none_for_a_draft_scored_before_this_review_existed(self):
        assert wr.review_view({"comedy_score": 50, "feedback": "old"}) is None
        assert wr.review_view(None) is None

    def test_review_view_exposes_only_what_the_page_shows(self):
        view = wr.review_view({"score": 80, "passes_bar": True, "dimensions": {}, "suggestions": [], "grounding": {"x": 1}, "references": [1]})
        assert view["score"] == 80 and "grounding" not in view and "references" not in view

"""plan_ltx25_segments is the "no surprises" preview: it must describe exactly what the render loop sends.

Each test runs the REAL render loop with the GPU, portrait/anchor fetches and video concat stubbed, and
compares the prompts and conditioning it handed to the workflow builder with the preview's."""
from types import SimpleNamespace

import pytest

from app.services import culturetoon_selfhosted_video as v


def _script(shots, hook_line="Premise", visual_style=None):
    return SimpleNamespace(shots=shots, hook_line=hook_line, scene_direction=None, visual_style=visual_style)


def _shot(n, seconds=8, focus="subject", **kw):
    base = {"shot_number": n, "duration_seconds": seconds, "shot_focus": focus, "camera_movement": "tracking",
            "subject_visual": f"Landing craft {n} plough through the surf", "people": "reference", "dialogue": "Spoken line here.",
            "narration": "external"}
    base.update(kw)
    return base


def _variant(vid, name):
    return SimpleNamespace(id=vid, name=name, image_url=f"https://cdn/{vid}.png", voice_description="calm",
                           character=SimpleNamespace(description=f"{name} is a woman"))


@pytest.fixture
def stubs(mocker):
    mocker.patch("app.media.ltx25_workflow.LTX25_MSR_ENABLED", False)
    mocker.patch("httpx.get", side_effect=lambda url, timeout=30: SimpleNamespace(content=b"photo"))
    mocker.patch("app.media.ltx25_workflow.build_backdrop_only_anchor", return_value=b"anchor")
    mocker.patch.object(v, "_fetch_portrait_anchor", return_value=b"portrait")
    mocker.patch.object(v, "_extract_last_frame_png", return_value=b"last-frame")
    mocker.patch.object(v, "_concat_video_segments", side_effect=lambda videos: b"|".join(videos))
    mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video")
    return SimpleNamespace(build=mocker.patch("app.media.ltx25_workflow.build_workflow", return_value={}))


def _rendered_prompts(stubs):
    return [call.args[0] for call in stubs.build.call_args_list]


class TestPreviewMatchesTheRender:
    def test_a_photo_anchored_world_video(self, stubs):
        shots = [_shot(1, scene_index=0), _shot(2, scene_index=1, people="none"), _shot(3, scene_index=2)]
        script = _script(shots, visual_style="illustrated_history")
        backgrounds = {i: SimpleNamespace(image_url=f"https://cdn/{i}.jpg", name=f"Scene {i}") for i in range(3)}
        plan = v.plan_ltx25_segments(script, [], None, backgrounds)
        v.generate_toon_video_ltx25(script, [], "endpoint", scene_backgrounds=backgrounds)
        assert _rendered_prompts(stubs) == [seg["prompt"] for seg in plan]
        assert [c.kwargs["image_strength"] for c in stubs.build.call_args_list] == [seg["image_strength"] for seg in plan] == [0.5] * 3
        assert [seg["opening_frame"]["url"] for seg in plan] == [f"https://cdn/{i}.jpg" for i in range(3)]
        assert all(seg["mode"] == "subject_only" for seg in plan)

    def test_a_world_video_without_photos_opens_on_a_blank_canvas_at_the_default_strength(self, stubs):
        script = _script([_shot(1), _shot(2)])
        plan = v.plan_ltx25_segments(script, [], None, None)
        v.generate_toon_video_ltx25(script, [], "endpoint")
        assert _rendered_prompts(stubs) == [seg["prompt"] for seg in plan]
        assert plan[0]["opening_frame"]["kind"] == "blank_canvas" and plan[0]["image_strength"] is None
        assert stubs.build.call_args.kwargs["image_strength"] is None

    def test_a_hosted_video_chains_segments_from_the_same_speaker_and_scene(self, stubs):
        zara = _variant("z", "Zara")
        shots = [_shot(i, seconds=10, focus="character", speaker_variant_id="z", scene_index=0, people=None,
                       shot_type="medium", action="talks", dialogue=f"Line {i}", narration=None) for i in (1, 2, 3)]
        script = _script(shots)
        plan = v.plan_ltx25_segments(script, [zara], None, None)
        v.generate_toon_video_ltx25(script, [zara], "endpoint")
        assert len(plan) >= 2
        assert _rendered_prompts(stubs) == [seg["prompt"] for seg in plan]
        assert [seg["opening_frame"]["kind"] for seg in plan] == \
            ["character_portrait"] + ["previous_segment_last_frame"] * (len(plan) - 1)
        assert "direct continuation" in plan[1]["prompt"] and "direct continuation" not in plan[0]["prompt"]

    def test_a_speaker_change_is_a_cut_back_to_a_fresh_portrait(self, stubs):
        zara, hans = _variant("z", "Zara"), _variant("h", "Hans")
        shots = [_shot(1, seconds=8, focus="character", speaker_variant_id="z", scene_index=0, people=None, dialogue="Hi", narration=None),
                 _shot(2, seconds=8, focus="character", speaker_variant_id="h", scene_index=0, people=None, dialogue="Hello", narration=None)]
        script = _script(shots)
        plan = v.plan_ltx25_segments(script, [zara, hans], None, None)
        v.generate_toon_video_ltx25(script, [zara, hans], "endpoint")
        assert _rendered_prompts(stubs) == [seg["prompt"] for seg in plan]
        assert [seg["opening_frame"]["kind"] for seg in plan] == ["character_portrait", "character_portrait"]
        assert [seg["opening_frame"]["name"] for seg in plan] == ["Zara", "Hans"]

    def test_a_subject_segment_after_a_character_segment_resets_the_chain(self, stubs):
        zara = _variant("z", "Zara")
        shots = [_shot(1, seconds=8, focus="character", speaker_variant_id="z", scene_index=0, people=None, dialogue="Hi", narration=None),
                 _shot(2, seconds=8, focus="subject", scene_index=1),
                 _shot(3, seconds=8, focus="character", speaker_variant_id="z", scene_index=2, people=None, dialogue="Bye", narration=None)]
        script = _script(shots)
        plan = v.plan_ltx25_segments(script, [zara], None, None)
        v.generate_toon_video_ltx25(script, [zara], "endpoint")
        assert _rendered_prompts(stubs) == [seg["prompt"] for seg in plan]
        assert [seg["mode"] for seg in plan] == ["character", "subject_only", "character"]
        assert plan[2]["opening_frame"]["kind"] == "character_portrait"

    def test_the_plan_reports_segment_seconds_and_shot_numbers(self, stubs):
        script = _script([_shot(1, 8, scene_index=0), _shot(2, 9, scene_index=1)])
        plan = v.plan_ltx25_segments(script, [], None, None)
        assert [(s["index"], s["shot_numbers"], s["seconds"]) for s in plan] == [(1, [1], 8), (2, [2], 9)]
        assert plan[0]["negative_prompt"].startswith("blurry")

    def test_planning_needs_no_network_and_renders_nothing(self, mocker):
        mocker.patch("app.media.ltx25_workflow.LTX25_MSR_ENABLED", False)
        get, run = mocker.patch("httpx.get"), mocker.patch("app.media.runpod_serverless_client.run_inference_job")
        v.plan_ltx25_segments(_script([_shot(1, scene_index=0)]), [], None,
                              {0: SimpleNamespace(image_url="https://cdn/0.jpg", name="s")})
        get.assert_not_called()
        run.assert_not_called()


ROME = {"label": "Ancient Rome, 753 BC to 27 BC", "start_year": -753, "end_year": -27}


def _era_script(era, shots=None):
    script = _script(shots or [_shot(1), _shot(2)])
    script.comedy_judgment = {"era": era} if era else {}
    return script


class TestEraInThePrompt:
    """A render of Rome in 753 BC showed jeeps: the prompt never said when it was set and the boilerplate asked
    for 'vehicles'. Every segment now opens with the era, and no World prompt names a vehicle."""

    def test_every_segment_opens_with_the_era_and_what_the_period_looked_like(self):
        plan = v.plan_ltx25_segments(_era_script(ROME), [], None, None)
        assert len(plan) == 2
        for seg in plan:
            assert seg["prompt"].startswith("Ancient Rome, 753 BC to 27 BC. Set in the ancient world")
            assert "terracotta" in seg["prompt"] and "Everything on screen belongs to this period" in seg["prompt"]

    def test_the_era_comes_before_the_premise_and_the_shot(self):
        prompt = v.plan_ltx25_segments(_era_script(ROME), [], None, None)[0]["prompt"]
        assert prompt.index("Ancient Rome") < prompt.index("Premise:") < prompt.index("SHOT 1")

    @pytest.mark.parametrize("era", [ROME, None, {"label": "Normandy, June 1944", "start_year": 1944, "end_year": 1944}])
    def test_no_prompt_asks_the_model_to_animate_vehicles(self, era):
        for seg in v.plan_ltx25_segments(_era_script(era), [], None, None):
            assert "vehicle" not in seg["prompt"].lower()
            assert "everything in the scene that can move keeps moving" in seg["prompt"]

    def test_a_script_with_no_era_is_prompted_exactly_as_before_apart_from_the_motion_line(self):
        prompt = v.plan_ltx25_segments(_era_script(None), [], None, None)[0]["prompt"]
        assert prompt.startswith("Premise: Premise")

    def test_a_toon_script_is_untouched(self):
        # Toon scripts carry a comedy judgment too, but never an era.
        script = _script([_shot(1)])
        script.comedy_judgment = {"comedy_score": 70, "passes_bar": True}
        assert not v.plan_ltx25_segments(script, [], None, None)[0]["prompt"].startswith("Ancient")
        assert v.script_era(SimpleNamespace(comedy_judgment=None)) is None
        assert v.script_era(SimpleNamespace(comedy_judgment="not a dict")) is None
        assert v.script_era(SimpleNamespace()) is None


class TestEraNegativePrompt:
    def test_an_ancient_script_adds_the_modern_things_to_the_negative_prompt(self):
        neg = v.plan_ltx25_segments(_era_script(ROME), [], None, None)[0]["negative_prompt"]
        assert neg.startswith("blurry") and "cars, trucks, jeeps" in neg and "asphalt roads" in neg and "khaki" in neg

    def test_a_modern_or_unknown_era_keeps_the_standard_negative_prompt(self):
        from app.media import ltx25_workflow
        for era in (None, {"label": "Normandy, June 1944", "start_year": 1944, "end_year": 1944}):
            neg = v.plan_ltx25_segments(_era_script(era), [], None, None)[0]["negative_prompt"]
            assert neg == ltx25_workflow.DEFAULT_NEGATIVE_PROMPT

    def test_the_render_sends_exactly_the_negative_prompt_the_preview_shows(self, stubs):
        script = _era_script(ROME)
        plan = v.plan_ltx25_segments(script, [], None, None)
        v.generate_toon_video_ltx25(script, [], "endpoint")
        sent = [c.kwargs["negative_prompt"] for c in stubs.build.call_args_list]
        assert sent == [seg["negative_prompt"] for seg in plan] and "jeeps" in sent[0]
        assert _rendered_prompts(stubs) == [seg["prompt"] for seg in plan]

    def test_a_hosted_video_gets_the_era_negative_prompt_too(self, stubs):
        zara = _variant("z", "Zara")
        shots = [_shot(1, seconds=8, focus="character", speaker_variant_id="z", scene_index=0, people=None,
                       dialogue="Hi", narration=None)]
        script = _era_script(ROME, shots)
        v.generate_toon_video_ltx25(script, [zara], "endpoint")
        assert "jeeps" in stubs.build.call_args.kwargs["negative_prompt"]

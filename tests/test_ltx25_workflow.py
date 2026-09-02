"""Tests for app/media/ltx25_workflow.py — the LTX-2.5 graph builder."""
import json

import pytest

from app.media.ltx25_workflow import (
    DEFAULT_NEGATIVE_PROMPT, LTX25WorkflowError, MAIN_CLIP,
    TARGET_HEIGHT, TARGET_WIDTH, build_composite_anchor, build_workflow,
)


def _classes(workflow, class_type):
    return [n for n in workflow.values() if n["class_type"] == class_type]


class TestBuildWorkflow:
    def test_injects_prompt_duration_and_seed(self):
        workflow = build_workflow("a cosy living room scene", 12, seed=7)
        prompts = [n for n in _classes(workflow, "PrimitiveStringMultiline")
                   if isinstance(n["inputs"].get("value"), str)]
        assert any(n["inputs"]["value"] == "a cosy living room scene" for n in prompts)
        assert any(n["inputs"].get("value") == 12 for n in _classes(workflow, "PrimitiveInt"))
        assert all(n["inputs"]["noise_seed"] == 7 for n in _classes(workflow, "RandomNoise")
                   if isinstance(n["inputs"].get("noise_seed"), int))

    def test_default_negative_prompt_targets_identity_drift(self):
        """With no per-character LoRA, the negative prompt plus the anchor
        are the only things holding identity across cuts."""
        workflow = build_workflow("scene", 8)
        texts = [n["inputs"]["text"] for n in _classes(workflow, "CLIPTextEncode")
                 if isinstance(n["inputs"].get("text"), str)]
        assert any("inconsistent identity" in t for t in texts)
        assert any(t == DEFAULT_NEGATIVE_PROMPT for t in texts)

    def test_explicit_negative_prompt_overrides_the_default(self):
        workflow = build_workflow("scene", 8, negative_prompt="just this")
        texts = [n["inputs"]["text"] for n in _classes(workflow, "CLIPTextEncode")
                 if isinstance(n["inputs"].get("text"), str)]
        assert "just this" in texts

    def test_resize_node_is_removed_and_consumers_rewired(self):
        """Its resize_type is a COMFY_DYNAMICCOMBO_V3 that passes ComfyUI's
        validator but fails at execution. Callers supply an anchor already
        at the target size, so dropping it changes nothing in the sampling
        path — but its consumers must not be left dangling."""
        workflow = build_workflow("scene", 8)
        assert not _classes(workflow, "ResizeImageMaskNode")
        node_ids = set(workflow)
        dangling = [
            (nid, key) for nid, node in workflow.items()
            for key, value in node["inputs"].items()
            if isinstance(value, list) and len(value) == 2
            and isinstance(value[0], str) and value[0] not in node_ids
        ]
        assert dangling == []

    def test_save_video_gets_format_and_codec(self):
        """The UI->API converter's schema walk doesn't surface these, and
        without them execution reaches the final node and dies."""
        workflow = build_workflow("scene", 8)
        for node in _classes(workflow, "SaveVideo"):
            assert node["inputs"]["format"] == "auto"
            assert node["inputs"]["codec"] == "auto"

    def test_every_clip_loader_points_at_the_downloaded_encoder(self):
        """The template pins an optional enhancer CLIP we don't ship;
        ComfyUI rejects an unknown filename even on an unused node."""
        workflow = build_workflow("scene", 8)
        assert all(n["inputs"]["clip_name"] == MAIN_CLIP for n in _classes(workflow, "CLIPLoader"))

    def test_prompt_enhancement_is_disabled(self):
        workflow = build_workflow("scene", 8)
        for node in _classes(workflow, "PrimitiveBoolean"):
            if isinstance(node["inputs"].get("value"), bool):
                assert node["inputs"]["value"] is False

    def test_missing_workflow_file_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LTX25_WORKFLOW_PATH", str(tmp_path / "nope.json"))
        with pytest.raises(LTX25WorkflowError):
            build_workflow("scene", 8)

    def test_each_call_returns_an_independent_copy(self):
        first = build_workflow("first prompt", 8)
        second = build_workflow("second prompt", 8)
        values = [n["inputs"]["value"] for n in _classes(first, "PrimitiveStringMultiline")
                  if isinstance(n["inputs"].get("value"), str)]
        assert "first prompt" in values


class TestCompositeAnchor:
    def _png(self, size=(1024, 1024), colour=(200, 100, 50)):
        from io import BytesIO
        from PIL import Image
        buf = BytesIO()
        Image.new("RGB", size, colour).save(buf, format="PNG")
        return buf.getvalue()

    def test_composites_every_portrait_into_one_target_sized_frame(self):
        """Image conditioning propagates whatever the FIRST FRAME contains,
        so every identity that must persist has to be in it — one portrait
        can only ever carry one face."""
        from io import BytesIO
        from PIL import Image

        anchor = build_composite_anchor([self._png(colour=c) for c in
                                         ((255, 0, 0), (0, 255, 0), (0, 0, 255))])
        image = Image.open(BytesIO(anchor))
        assert image.size == (TARGET_WIDTH, TARGET_HEIGHT)
        # Each third should carry its own portrait's colour.
        third = TARGET_WIDTH // 3
        assert image.getpixel((third // 2, TARGET_HEIGHT // 2))[0] > 200      # red slot
        assert image.getpixel((third + third // 2, TARGET_HEIGHT // 2))[1] > 200  # green slot

    def test_single_character_fills_the_frame(self):
        from io import BytesIO
        from PIL import Image
        anchor = build_composite_anchor([self._png()])
        assert Image.open(BytesIO(anchor)).size == (TARGET_WIDTH, TARGET_HEIGHT)

    def test_none_entries_are_skipped(self):
        """A character whose portrait couldn't be fetched shouldn't break the
        anchor for everyone else — it just isn't anchored."""
        from io import BytesIO
        from PIL import Image
        anchor = build_composite_anchor([None, self._png(), None])
        assert Image.open(BytesIO(anchor)).size == (TARGET_WIDTH, TARGET_HEIGHT)

    def test_no_usable_images_raises(self):
        with pytest.raises(LTX25WorkflowError):
            build_composite_anchor([None, None])

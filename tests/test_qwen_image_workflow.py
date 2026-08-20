"""Tests for app/media/qwen_image_workflow.py's class_type-based node
injection."""
import json
import os

import pytest

from app.media.qwen_image_workflow import build_workflow, load_workflow_template, QwenImageWorkflowError


@pytest.fixture
def fixture_workflow_path(tmp_path):
    workflow = {
        "10": {"class_type": "VAELoader", "inputs": {"vae_name": "vae.safetensors"}},
        "12": {"class_type": "UNETLoader", "inputs": {"unet_name": "unet.safetensors", "weight_dtype": "default"}},
        "41": {"class_type": "LoadImage", "inputs": {"image": ""}},
        "61": {"class_type": "CLIPLoader", "inputs": {"clip_name": "clip.safetensors", "type": "qwen_image"}},
        "65": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 20, "model": ["67", 0], "positive": ["68", 0], "negative": ["69", 0], "latent_image": ["66", 0]}},
        "66": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "67": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": 3.1, "model": ["12", 0]}},
        "68": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "", "clip": ["61", 0], "vae": ["10", 0], "image1": ["41", 0]}},
        "69": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "", "clip": ["61", 0], "vae": ["10", 0], "image1": ["41", 0]}},
    }
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow))
    return str(path)


@pytest.fixture(autouse=True)
def _use_fixture_path(fixture_workflow_path, monkeypatch):
    monkeypatch.setenv("QWEN_IMAGE_WORKFLOW_PATH", fixture_workflow_path)


class TestLoadWorkflowTemplate:
    def test_loads_from_env_path(self, fixture_workflow_path):
        workflow = load_workflow_template()
        assert workflow["12"]["class_type"] == "UNETLoader"

    def test_missing_file_raises(self, monkeypatch):
        monkeypatch.setenv("QWEN_IMAGE_WORKFLOW_PATH", "/nonexistent/path.json")
        with pytest.raises(QwenImageWorkflowError):
            load_workflow_template()


class TestBuildWorkflow:
    def test_injects_prompt_into_first_positive_node_only(self):
        workflow = build_workflow("make them smile", "ref.png")
        assert workflow["68"]["inputs"]["prompt"] == "make them smile"
        # The second TextEncodeQwenImageEditPlus (negative, by node id
        # order) must stay untouched — matches the official example's own
        # empty-prompt negative exactly.
        assert workflow["69"]["inputs"]["prompt"] == ""

    def test_injects_reference_filename_into_every_load_image_node(self):
        workflow = build_workflow("prompt", "my-ref-abc123.png")
        assert workflow["41"]["inputs"]["image"] == "my-ref-abc123.png"

    def test_injects_seed_when_given(self):
        workflow = build_workflow("prompt", "ref.png", seed=42)
        assert workflow["65"]["inputs"]["seed"] == 42

    def test_no_seed_leaves_default_untouched(self):
        workflow = build_workflow("prompt", "ref.png")
        assert workflow["65"]["inputs"]["seed"] == 0

    def test_original_template_not_mutated(self, fixture_workflow_path):
        build_workflow("mutated prompt", "ref.png")
        reloaded = load_workflow_template()
        assert reloaded["68"]["inputs"]["prompt"] == ""

    def test_missing_prompt_node_raises(self, tmp_path, monkeypatch):
        workflow = {"41": {"class_type": "LoadImage", "inputs": {"image": ""}}}
        path = tmp_path / "no_prompt.json"
        path.write_text(json.dumps(workflow))
        monkeypatch.setenv("QWEN_IMAGE_WORKFLOW_PATH", str(path))
        with pytest.raises(QwenImageWorkflowError):
            build_workflow("prompt", "ref.png")

    def test_missing_load_image_node_raises(self, tmp_path, monkeypatch):
        workflow = {"68": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": ""}}}
        path = tmp_path / "no_image.json"
        path.write_text(json.dumps(workflow))
        monkeypatch.setenv("QWEN_IMAGE_WORKFLOW_PATH", str(path))
        with pytest.raises(QwenImageWorkflowError):
            build_workflow("prompt", "ref.png")

    def test_real_shipped_template_builds_successfully(self, monkeypatch):
        # Uses the actual app/media/workflows/qwen_image_edit.json, not
        # the fixture — confirms the real file this ships with is valid
        # and has exactly the nodes build_workflow expects.
        monkeypatch.delenv("QWEN_IMAGE_WORKFLOW_PATH", raising=False)
        workflow = build_workflow("a happy expression", "portrait.png")
        assert workflow["68"]["inputs"]["prompt"] == "a happy expression"
        assert workflow["41"]["inputs"]["image"] == "portrait.png"

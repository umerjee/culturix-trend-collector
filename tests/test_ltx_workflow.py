"""Tests for app/media/ltx_workflow.py's class_type-based node injection."""
import json
import os

import pytest

from app.media.ltx_workflow import build_workflow, load_workflow_template, LTXWorkflowError


@pytest.fixture
def fixture_workflow_path(tmp_path):
    workflow = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ltx.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive prompt"}, "inputs": {"text": "", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "_meta": {"title": "Negative prompt"}, "inputs": {"text": "blurry, low quality", "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": 720, "height": 1280, "length": 121, "batch_size": 1}},
        "5": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "", "strength_model": 1.0}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["5", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0], "seed": 0, "steps": 30, "cfg": 3.0}},
    }
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow))
    return str(path)


@pytest.fixture(autouse=True)
def _use_fixture_path(fixture_workflow_path, monkeypatch):
    monkeypatch.setenv("LTX_WORKFLOW_PATH", fixture_workflow_path)


class TestLoadWorkflowTemplate:
    def test_loads_from_env_path(self, fixture_workflow_path):
        workflow = load_workflow_template()
        assert workflow["1"]["class_type"] == "CheckpointLoaderSimple"

    def test_missing_file_raises(self, monkeypatch):
        monkeypatch.setenv("LTX_WORKFLOW_PATH", "/nonexistent/path.json")
        with pytest.raises(LTXWorkflowError):
            load_workflow_template()


class TestBuildWorkflow:
    def test_injects_prompt_into_empty_text_encode_node_only(self):
        workflow = build_workflow("a character waves hello", duration_seconds=5)
        assert workflow["2"]["inputs"]["text"] == "a character waves hello"
        # The negative prompt node (non-empty starting text) must be untouched.
        assert workflow["3"]["inputs"]["text"] == "blurry, low quality"

    def test_injects_lora_path_when_given(self):
        workflow = build_workflow("prompt", duration_seconds=5, lora_path="my_character.safetensors")
        assert workflow["5"]["inputs"]["lora_name"] == "my_character.safetensors"

    def test_no_lora_path_removes_lora_node_and_rewires_around_it(self):
        # Confirmed live 2026-08-20: leaving the node in place with an empty
        # lora_name is not a safe no-op — ComfyUI validates lora_name
        # against the volume's actual LoRA files, and with zero trained
        # yet that dropdown has no valid values, so even "" gets rejected.
        workflow = build_workflow("prompt", duration_seconds=5)
        assert "5" not in workflow
        # KSampler's model input pointed at the LoRA node (["5", 0]) —
        # it must now point directly at the LoRA node's own upstream
        # model input instead (["1", 0], the checkpoint's model output).
        assert workflow["6"]["inputs"]["model"] == ["1", 0]

    def test_injects_duration_as_frames(self):
        workflow = build_workflow("prompt", duration_seconds=5)
        assert workflow["4"]["inputs"]["length"] == 120  # 5s * 24fps

    def test_injects_seed_when_given(self):
        workflow = build_workflow("prompt", duration_seconds=5, seed=42)
        assert workflow["6"]["inputs"]["seed"] == 42

    def test_original_template_not_mutated(self, fixture_workflow_path):
        build_workflow("mutated prompt", duration_seconds=5)
        reloaded = load_workflow_template()
        assert reloaded["2"]["inputs"]["text"] == ""

    def test_missing_prompt_node_raises(self, tmp_path, monkeypatch):
        workflow = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {}}}
        path = tmp_path / "no_prompt.json"
        path.write_text(json.dumps(workflow))
        monkeypatch.setenv("LTX_WORKFLOW_PATH", str(path))
        with pytest.raises(LTXWorkflowError):
            build_workflow("prompt", duration_seconds=5)

    def test_lora_path_given_but_no_lora_node_raises(self, tmp_path, monkeypatch):
        workflow = {"2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}}
        path = tmp_path / "no_lora.json"
        path.write_text(json.dumps(workflow))
        monkeypatch.setenv("LTX_WORKFLOW_PATH", str(path))
        with pytest.raises(LTXWorkflowError):
            build_workflow("prompt", duration_seconds=5, lora_path="x.safetensors")

    def test_title_based_selection_wins_even_when_both_nodes_have_text(self, tmp_path, monkeypatch):
        # Regression test: the real official LTX-2.3 template ships both its
        # positive AND negative CLIPTextEncode nodes with non-empty
        # placeholder text, which would defeat an empty-text-only heuristic.
        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ltx.safetensors"}},
            "2": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive Prompt"}, "inputs": {"text": "placeholder positive"}},
            "3": {"class_type": "CLIPTextEncode", "_meta": {"title": "Negative Prompt"}, "inputs": {"text": "placeholder negative"}},
        }
        path = tmp_path / "titled.json"
        path.write_text(json.dumps(workflow))
        monkeypatch.setenv("LTX_WORKFLOW_PATH", str(path))

        result = build_workflow("a character waves hello", duration_seconds=5)

        assert result["2"]["inputs"]["text"] == "a character waves hello"
        assert result["3"]["inputs"]["text"] == "placeholder negative"

    def test_injects_seed_into_random_noise_when_present(self, tmp_path, monkeypatch):
        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ltx.safetensors"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": 0, "control_after_generate": "fixed"}},
            "6": {"class_type": "KSampler", "inputs": {"seed": 0}},
        }
        path = tmp_path / "random_noise.json"
        path.write_text(json.dumps(workflow))
        monkeypatch.setenv("LTX_WORKFLOW_PATH", str(path))

        result = build_workflow("prompt", duration_seconds=5, seed=99)

        assert result["9"]["inputs"]["noise_seed"] == 99
        # RandomNoise takes priority — KSampler.seed is left untouched.
        assert result["6"]["inputs"]["seed"] == 0

"""Loads the ComfyUI API-format LTX-2 workflow template and injects a
job's prompt/LoRA/duration into it by matching each node's `class_type`
rather than hardcoded numeric node IDs — robust to minor differences in how
the workflow graph is laid out (e.g. if you rebuild/re-export it in the
ComfyUI GUI, node IDs can shift but class_type names won't).
"""
import copy
import json
import logging
import os
from typing import Optional

logger = logging.getLogger("culturix.media.ltx_workflow")

_DEFAULT_WORKFLOW_PATH = os.path.join(
    os.path.dirname(__file__), "workflows", "ltx_text_to_video.json"
)

# class_type values expected in the shipped default workflow — see that
# file's own header comment for which ComfyUI-LTXVideo node types these map
# to. If you rebuild the workflow with different node types, update these.
_PROMPT_NODE_CLASS = "CLIPTextEncode"
_LORA_NODE_CLASS = "LoraLoader"
_SAMPLER_NODE_CLASS = "KSampler"
# UNVERIFIED — ComfyUI-LTXVideo's empty-latent-video node's exact class_type
# and its length field's name/units (frames vs seconds) haven't been
# confirmed against a live install. Duration injection is skipped (a no-op,
# not an error) if this node type isn't present in your real workflow, so a
# guess here can't break job submission — just means duration silently
# falls back to whatever the template's own default is until this is fixed.
_LATENT_VIDEO_NODE_CLASS = "EmptyLTXVLatentVideo"
_DEFAULT_FPS = 24


class LTXWorkflowError(Exception):
    pass


def load_workflow_template() -> dict:
    path = os.getenv("LTX_WORKFLOW_PATH") or _DEFAULT_WORKFLOW_PATH
    if not os.path.exists(path):
        raise LTXWorkflowError(f"LTX workflow template not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _nodes_of_class(workflow: dict, class_type: str) -> list:
    return [node_id for node_id, node in workflow.items() if node.get("class_type") == class_type]


def build_workflow(prompt_text: str, duration_seconds: float, lora_path: Optional[str] = None,
                    seed: Optional[int] = None) -> dict:
    """Returns a deep copy of the loaded template with the prompt text (and
    optionally a LoRA path / duration / seed) injected. Raises
    LTXWorkflowError if the template doesn't contain the expected node
    types — a clear failure at build time rather than a confusing rejection
    from ComfyUI itself."""
    workflow = copy.deepcopy(load_workflow_template())

    prompt_nodes = _nodes_of_class(workflow, _PROMPT_NODE_CLASS)
    if not prompt_nodes:
        raise LTXWorkflowError(f"No {_PROMPT_NODE_CLASS} node found in the workflow template")
    for node_id in prompt_nodes:
        # Only the *positive* prompt encode node should get the job's text —
        # a workflow with a separate negative-prompt CLIPTextEncode node
        # must keep its own text untouched. Heuristic: the negative node's
        # existing text is non-empty and this is the only signal available
        # without a documented "negative" flag in ComfyUI's node schema
        # itself, so an empty-text CLIPTextEncode node is treated as the one
        # meant to receive the job's prompt.
        existing_text = (workflow[node_id].get("inputs") or {}).get("text", "")
        if not existing_text:
            workflow[node_id]["inputs"]["text"] = prompt_text

    if lora_path:
        lora_nodes = _nodes_of_class(workflow, _LORA_NODE_CLASS)
        if not lora_nodes:
            raise LTXWorkflowError(f"lora_path given but no {_LORA_NODE_CLASS} node found in the workflow template")
        for node_id in lora_nodes:
            workflow[node_id]["inputs"]["lora_name"] = lora_path

    if seed is not None:
        for node_id in _nodes_of_class(workflow, _SAMPLER_NODE_CLASS):
            workflow[node_id]["inputs"]["seed"] = seed

    latent_video_nodes = _nodes_of_class(workflow, _LATENT_VIDEO_NODE_CLASS)
    if latent_video_nodes and duration_seconds:
        frames = max(1, round(duration_seconds * _DEFAULT_FPS))
        for node_id in latent_video_nodes:
            workflow[node_id]["inputs"]["length"] = frames
    elif duration_seconds and not latent_video_nodes:
        logger.warning(
            "Workflow template has no %s node — duration_seconds=%s was not injected, "
            "falling back to the template's own default length",
            _LATENT_VIDEO_NODE_CLASS, duration_seconds,
        )

    return workflow

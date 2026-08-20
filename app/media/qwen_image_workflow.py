"""Loads the ComfyUI API-format Qwen-Image-Edit workflow template and
injects a job's prompt text and reference-image filename, matching each
node by `class_type` rather than hardcoded numeric node IDs — same
robustness reasoning as app/media/ltx_workflow.py.

The template itself (app/media/workflows/qwen_image_edit.json) is not a
guess: extracted directly from the PNG metadata of ComfyUI's own official
example (comfyanonymous/ComfyUI_examples, qwen_image/
qwen_image_edit_2509_basic_example.png, 2026-08-20) — every node,
parameter, and value (steps=20, cfg=4.0, sampler=euler, scheduler=simple,
ModelSamplingAuraFlow shift=3.1, 1024x1024 EmptySD3LatentImage) is
confirmed-working, not assembled from node class definitions alone. Only
the prompt text and reference-image filename are parameterized here;
everything else is left exactly as the official example had it.
"""
import copy
import json
import logging
import os
from typing import Optional

logger = logging.getLogger("culturix.media.qwen_image_workflow")

_DEFAULT_WORKFLOW_PATH = os.path.join(
    os.path.dirname(__file__), "workflows", "qwen_image_edit.json"
)

_POSITIVE_PROMPT_NODE_CLASS = "TextEncodeQwenImageEditPlus"
_LOAD_IMAGE_NODE_CLASS = "LoadImage"


class QwenImageWorkflowError(Exception):
    pass


def load_workflow_template() -> dict:
    path = os.getenv("QWEN_IMAGE_WORKFLOW_PATH") or _DEFAULT_WORKFLOW_PATH
    if not os.path.exists(path):
        raise QwenImageWorkflowError(f"Qwen-Image workflow template not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _nodes_of_class(workflow: dict, class_type: str) -> list:
    return [node_id for node_id, node in workflow.items() if node.get("class_type") == class_type]


def build_workflow(prompt_text: str, reference_image_filename: str, seed: Optional[int] = None) -> dict:
    """Returns a deep copy of the loaded template with the edit prompt and
    reference-image filename injected. reference_image_filename must
    already be uploaded to the Serverless job's ComfyUI instance via the
    job's own input.images field (see runpod_serverless_image_client.py) —
    this only wires the filename into the workflow's LoadImage node,
    it doesn't upload anything itself.

    Only the FIRST TextEncodeQwenImageEditPlus node (by node id order,
    which matches the template's own "Positive" node) gets the prompt —
    the second stays the empty-string negative, exactly matching the
    official example this template was extracted from. A template with a
    different node count/order would need a title-based selection instead
    (see ltx_workflow.py's _select_positive_prompt_nodes for that
    pattern) — not needed here since this module owns its own fixed
    template, unlike ltx_workflow.py which also has to tolerate hand-built
    variants.

    Raises QwenImageWorkflowError if the template doesn't contain the
    expected node types — a clear failure at build time rather than a
    confusing rejection from ComfyUI itself."""
    workflow = copy.deepcopy(load_workflow_template())

    prompt_nodes = _nodes_of_class(workflow, _POSITIVE_PROMPT_NODE_CLASS)
    if not prompt_nodes:
        raise QwenImageWorkflowError(f"No {_POSITIVE_PROMPT_NODE_CLASS} node found in the workflow template")
    positive_node_id = sorted(prompt_nodes, key=int)[0]
    workflow[positive_node_id]["inputs"]["prompt"] = prompt_text

    image_nodes = _nodes_of_class(workflow, _LOAD_IMAGE_NODE_CLASS)
    if not image_nodes:
        raise QwenImageWorkflowError(f"No {_LOAD_IMAGE_NODE_CLASS} node found in the workflow template")
    for node_id in image_nodes:
        workflow[node_id]["inputs"]["image"] = reference_image_filename

    if seed is not None:
        sampler_nodes = _nodes_of_class(workflow, "KSampler")
        for node_id in sampler_nodes:
            workflow[node_id]["inputs"]["seed"] = seed

    return workflow

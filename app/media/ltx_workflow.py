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
#
# Confirmed against a live RunPod validation run of the OFFICIAL "LTX-2.3:
# Text to Video" ComfyUI template (2026-08-18) — this is real, not guessed:
#   - EmptyLTXVLatentVideo: class_type confirmed correct, `length` is frames
#     (not seconds) — the guess in an earlier version of this file was right.
#   - fps: the real template's node literally titled "fps" defaults to 24
#     (matches this file's prior default, so no change) — but note the
#     template *also* has a separate CreateVideo mux node hardcoded to 30
#     and an audio-latent node using 25 for its own frame/rate math. These
#     three numbers are NOT the same knob; 24 is the one that lines up with
#     EmptyLTXVLatentVideo's frame-count field, which is what this module
#     actually injects into, so it's the right one to keep as our default —
#     just don't assume a single universal "fps" exists in a workflow this
#     complex if you rebuild it from scratch.
#   - Seed does NOT live on KSampler in the real template — LTX's official
#     workflow uses a RandomNoise node (input key `noise_seed`) feeding a
#     SamplerCustomAdvanced, not a plain KSampler. A simpler hand-built
#     workflow (like the one shipped by default here) can still legitimately
#     use plain KSampler though, since it's a generic node — so seed
#     injection below tries BOTH node types rather than picking one.
#   - LoRA slots: the real template has MULTIPLE distinct LoraLoader/
#     LoraLoaderModelOnly nodes for different purposes (a distilled speed
#     LoRA vs a text-encoder LoRA) — injecting a character LoRA into every
#     node of a given class_type is only correct when there's exactly ONE
#     such node in the graph. LoraLoaderModelOnly is the right class_type
#     for a model-only character/speed LoRA slot (confirmed from the real
#     template's own distilled-LoRA node) — build/maintain custom production
#     workflows with exactly one LoraLoaderModelOnly node for this to inject
#     correctly; a workflow with more than one will get the same character
#     LoRA applied to all of them, which is very likely wrong.
_PROMPT_NODE_CLASS = "CLIPTextEncode"
_LORA_NODE_CLASS = "LoraLoaderModelOnly"
# (class_type, seed input key) pairs to try, in order — see note above.
_SEED_NODE_CANDIDATES = [("RandomNoise", "noise_seed"), ("KSampler", "seed")]
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


def _select_positive_prompt_nodes(workflow: dict, prompt_nodes: list) -> list:
    """Picks which CLIPTextEncode node(s) should receive the job's prompt
    text. Prefers each node's `_meta.title` (present in any JSON exported via
    ComfyUI's "Save (API Format)") containing "positive" and not "negative" —
    confirmed necessary against the real official LTX-2.3 template, whose
    positive AND negative CLIPTextEncode nodes both ship with non-empty
    placeholder text, so the old empty-text-only heuristic would silently
    inject into neither. Falls back to the empty-text heuristic for
    hand-built templates (like this repo's own shipped default) that don't
    set titles."""
    titled = []
    for node_id in prompt_nodes:
        title = (workflow[node_id].get("_meta") or {}).get("title", "").lower()
        if "positive" in title and "negative" not in title:
            titled.append(node_id)
    if titled:
        return titled
    return [node_id for node_id in prompt_nodes if not (workflow[node_id].get("inputs") or {}).get("text", "")]


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
    for node_id in _select_positive_prompt_nodes(workflow, prompt_nodes):
        workflow[node_id]["inputs"]["text"] = prompt_text

    lora_nodes = _nodes_of_class(workflow, _LORA_NODE_CLASS)
    if lora_path:
        if not lora_nodes:
            raise LTXWorkflowError(f"lora_path given but no {_LORA_NODE_CLASS} node found in the workflow template")
        for node_id in lora_nodes:
            workflow[node_id]["inputs"]["lora_name"] = lora_path
    else:
        # The node's own _meta.title says "skipped if none" — this is that
        # skip. Confirmed live 2026-08-20 against the real Serverless
        # endpoint: leaving the node in the graph with an empty lora_name
        # is NOT a safe no-op — ComfyUI validates lora_name against the
        # actual files under models/loras/ on the volume, and with zero
        # LoRAs trained yet that dropdown has no valid values at all, so
        # even "" gets rejected ("lora_name: '' not in []"). Removing the
        # node and rewiring whatever consumed its output to its own
        # upstream `model` input bypasses it cleanly instead.
        for node_id in lora_nodes:
            upstream_model = (workflow[node_id].get("inputs") or {}).get("model")
            if upstream_model is None:
                logger.warning(
                    "%s node %s has no upstream 'model' input to rewire around — leaving it in place, "
                    "downstream nodes may fail validation", _LORA_NODE_CLASS, node_id,
                )
                continue
            for other_node in workflow.values():
                for key, value in (other_node.get("inputs") or {}).items():
                    if isinstance(value, list) and len(value) == 2 and value[0] == node_id:
                        other_node["inputs"][key] = upstream_model
            del workflow[node_id]

    if seed is not None:
        for class_type, seed_key in _SEED_NODE_CANDIDATES:
            seed_nodes = _nodes_of_class(workflow, class_type)
            if seed_nodes:
                for node_id in seed_nodes:
                    workflow[node_id]["inputs"][seed_key] = seed
                break

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

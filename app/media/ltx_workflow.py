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
_CHECKPOINT_NODE_CLASS = "CheckpointLoaderSimple"
_SAMPLER_NODE_CLASS = "KSampler"
_LOAD_IMAGE_NODE_CLASS = "LoadImage"
_IMG_TO_VIDEO_NODE_CLASS = "LTXVImgToVideo"
_CONDITIONING_NODE_CLASS = "LTXVConditioning"
_DEFAULT_FPS = 24
# Community-documented starting point for LTX-2's image-to-video strength
# (1.0 pins the first frame completely, 0.0 ignores the image entirely) —
# not tuned against our own outputs yet, just the ecosystem's own default.
_DEFAULT_IMG_STRENGTH = 0.8


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


def _next_node_id(workflow: dict) -> str:
    existing = [int(k) for k in workflow.keys() if k.lstrip("-").isdigit()]
    return str((max(existing) if existing else 0) + 1)


# Steers away from the specific failure modes seen in real output
# 2026-09-01: ghosting/double-exposure around a character's head, smeared
# or "melted" facial features, and the waxy plastic look LTX tends toward
# on faces. The template's own negative CLIPTextEncode node was previously
# left at whatever placeholder text it shipped with — build_workflow never
# wrote to it at all, so nothing was ever actually being steered away from
# despite the node existing and being wired into the sampler.
DEFAULT_NEGATIVE_PROMPT = (
    "blurry, out of focus, low quality, low resolution, compression artifacts, "
    "ghosting, double exposure, motion smear, warped face, melted features, "
    "distorted anatomy, deformed hands, extra limbs, extra fingers, "
    "disfigured, waxy skin, plastic skin, uncanny, flickering, "
    "watermark, text, caption, jpeg artifacts"
)


def build_workflow(prompt_text: str, duration_seconds: float, lora_path: Optional[str] = None,
                    seed: Optional[int] = None, reference_image_filename: Optional[str] = None,
                    negative_prompt: Optional[str] = None) -> dict:
    """Returns a deep copy of the loaded template with the prompt text (and
    optionally a LoRA path / duration / seed / reference image) injected.
    Raises LTXWorkflowError if the template doesn't contain the expected
    node types — a clear failure at build time rather than a confusing
    rejection from ComfyUI itself.

    reference_image_filename anchors the first frame on a real character
    photo (already uploaded to the pod's ComfyUI input directory — see
    deploy/runpod_serverless/handler.py's upload step, which is what
    supplies this filename) via LTXVImgToVideo, instead of generating
    purely from an empty/noise latent. Confirmed live 2026-08-29/30: pure
    text-to-video with only a character LoRA for identity (the LoRA
    trained on static reference images, never on motion) produced a video
    that was really just 2-3 held poses with abrupt transitions between
    them, not continuous animation — asking one LoRA to carry both
    identity AND not break the base model's motion generation turned out
    to be a harder ask than the ecosystem is actually built for.
    Image-to-video is LTX's own documented, well-supported pattern for
    grounding identity from a real photo while still letting the base
    model generate motion naturally from that anchor."""
    workflow = copy.deepcopy(load_workflow_template())

    prompt_nodes = _nodes_of_class(workflow, _PROMPT_NODE_CLASS)
    if not prompt_nodes:
        raise LTXWorkflowError(f"No {_PROMPT_NODE_CLASS} node found in the workflow template")
    positive_prompt_nodes = _select_positive_prompt_nodes(workflow, prompt_nodes)
    for node_id in positive_prompt_nodes:
        workflow[node_id]["inputs"]["text"] = prompt_text

    # Every prompt node that ISN'T positive is the negative one — same
    # split the image-to-video branch below already relies on. Defaults to
    # DEFAULT_NEGATIVE_PROMPT rather than leaving the template's shipped
    # placeholder text in place; pass negative_prompt="" to deliberately
    # send an empty negative instead.
    negative_text = DEFAULT_NEGATIVE_PROMPT if negative_prompt is None else negative_prompt
    for node_id in [n for n in prompt_nodes if n not in positive_prompt_nodes]:
        workflow[node_id]["inputs"]["text"] = negative_text

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
    frames = max(1, round(duration_seconds * _DEFAULT_FPS)) if duration_seconds else None

    if reference_image_filename:
        if not latent_video_nodes:
            raise LTXWorkflowError(
                f"reference_image_filename given but no {_LATENT_VIDEO_NODE_CLASS} node found to replace"
            )
        checkpoint_nodes = _nodes_of_class(workflow, _CHECKPOINT_NODE_CLASS)
        if not checkpoint_nodes:
            raise LTXWorkflowError(f"No {_CHECKPOINT_NODE_CLASS} node found for the VAE input")
        positive_nodes = _select_positive_prompt_nodes(workflow, prompt_nodes)
        negative_nodes = [n for n in prompt_nodes if n not in positive_nodes]
        if len(positive_nodes) != 1 or len(negative_nodes) != 1:
            raise LTXWorkflowError(
                "Image-to-video conditioning needs exactly one positive and one negative "
                f"{_PROMPT_NODE_CLASS} node, found {len(positive_nodes)} positive / {len(negative_nodes)} negative"
            )

        base_node_id = latent_video_nodes[0]
        base_inputs = workflow[base_node_id]["inputs"]

        load_image_id = _next_node_id(workflow)
        workflow[load_image_id] = {
            "class_type": _LOAD_IMAGE_NODE_CLASS,
            "_meta": {"title": "Character reference photo (injected by ltx_workflow.py)"},
            "inputs": {"image": reference_image_filename},
        }

        img2vid_id = _next_node_id(workflow)
        workflow[img2vid_id] = {
            "class_type": _IMG_TO_VIDEO_NODE_CLASS,
            "_meta": {"title": "Anchor first frame on character photo (injected by ltx_workflow.py)"},
            "inputs": {
                "positive": [positive_nodes[0], 0],
                "negative": [negative_nodes[0], 0],
                "vae": [checkpoint_nodes[0], 2],
                "image": [load_image_id, 0],
                "width": base_inputs.get("width", 720),
                "height": base_inputs.get("height", 1280),
                "length": frames or base_inputs.get("length", 97),
                "batch_size": base_inputs.get("batch_size", 1),
                "strength": _DEFAULT_IMG_STRENGTH,
            },
        }

        for node_id in _nodes_of_class(workflow, _SAMPLER_NODE_CLASS):
            workflow[node_id]["inputs"]["positive"] = [img2vid_id, 0]
            workflow[node_id]["inputs"]["negative"] = [img2vid_id, 1]
            workflow[node_id]["inputs"]["latent_image"] = [img2vid_id, 2]

        del workflow[base_node_id]
    elif latent_video_nodes and frames:
        for node_id in latent_video_nodes:
            workflow[node_id]["inputs"]["length"] = frames
    elif duration_seconds and not latent_video_nodes:
        logger.warning(
            "Workflow template has no %s node — duration_seconds=%s was not injected, "
            "falling back to the template's own default length",
            _LATENT_VIDEO_NODE_CLASS, duration_seconds,
        )

    _ensure_ltxv_conditioning(workflow)
    return workflow


def _ensure_ltxv_conditioning(workflow: dict) -> None:
    """Inserts an LTXVConditioning node between whatever currently feeds the
    sampler's conditioning and the sampler itself.

    Confirmed live 2026-09-01: real generations came back as a series of
    near-static held poses — "a collection of images", not animation — and
    this workflow template had NO LTXVConditioning node at all. Per
    ComfyUI's own node docs it "adds frame rate information to both
    positive and negative conditioning inputs", so that timing and motion
    are interpreted consistently; without it the model is given no
    frame-rate signal whatsoever, which is a documented cause of flat/low
    motion output. The template was hand-built (see this module's header)
    rather than exported from an official LTX graph, which is how the node
    came to be missing.

    Runs for BOTH the image-to-video and text-to-video paths, taking the
    sampler's current positive/negative sources — so it correctly chains
    after LTXVImgToVideo when that branch injected one, and straight off
    the CLIPTextEncode nodes otherwise. Placement is inferred from the
    node's signature (it consumes and returns conditioning, so it belongs
    between the conditioning source and the sampler); ComfyUI's docs page
    doesn't state graph position explicitly.

    frame_rate is set to _DEFAULT_FPS so it matches the CreateVideo node's
    own fps and the frame count derived from duration_seconds — a
    mismatch here would make generated motion play at the wrong speed.
    """
    sampler_nodes = _nodes_of_class(workflow, _SAMPLER_NODE_CLASS)
    if not sampler_nodes:
        logger.warning(
            "No %s node found — skipping %s injection",
            _SAMPLER_NODE_CLASS, _CONDITIONING_NODE_CLASS,
        )
        return
    if _nodes_of_class(workflow, _CONDITIONING_NODE_CLASS):
        return  # template already supplies one — don't double up

    for sampler_id in sampler_nodes:
        inputs = workflow[sampler_id].get("inputs") or {}
        positive_src, negative_src = inputs.get("positive"), inputs.get("negative")
        if not positive_src or not negative_src:
            continue
        cond_id = _next_node_id(workflow)
        workflow[cond_id] = {
            "class_type": _CONDITIONING_NODE_CLASS,
            "_meta": {"title": "Frame-rate conditioning (injected by ltx_workflow.py)"},
            "inputs": {
                "positive": positive_src,
                "negative": negative_src,
                "frame_rate": float(_DEFAULT_FPS),
            },
        }
        workflow[sampler_id]["inputs"]["positive"] = [cond_id, 0]
        workflow[sampler_id]["inputs"]["negative"] = [cond_id, 1]

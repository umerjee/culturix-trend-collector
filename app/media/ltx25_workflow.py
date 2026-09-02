"""Builds a ready-to-submit LTX-2.5 ComfyUI graph.

Separate from ltx_workflow.py (LTX-2.3) rather than an extension of it —
the two graphs share almost nothing structurally:

  2.3: CheckpointLoaderSimple -> LoraLoaderModelOnly -> KSampler,
       one generation PER SHOT, narration synthesized separately
       (Chatterbox) and muxed on with ffmpeg afterwards.
  2.5: UNETLoader + separate video/audio VAEs + Gemma-4 CLIP, two-stage
       sampling through LTXVDualCFGGuider with a latent upsampler, and
       audio denoised JOINTLY with video
       (LTXVEmptyLatentAudio -> LTXVConcatAVLatent -> LTXVSeparateAVLatent
       -> LTXVAudioVAEDecode).

Two consequences worth stating plainly, because they delete code rather
than add it:

  * No per-character LoRA. Identity is carried by image conditioning from
    the first frame, so a COMPOSITE anchor (every cast member's real
    portrait side by side) carries the whole cast. LoRAs are version-locked
    to a base model, so this also removes retraining on every future LTX
    upgrade.
  * No narration mux and no last-frame chaining. 2.5 generates synchronized
    audio natively and holds a scene across cuts in one generation, which
    is what those two workarounds existed to approximate.

The graph itself is the OFFICIAL Comfy-Org template, converted UI->API by
scripts/convert_comfy_workflow.py against a live ComfyUI's /object_info.
It is deliberately not hand-simplified: the LTX-2.3 workflow was, and that
is how it silently lost its LTXVConditioning node and produced near-static
output for weeks.
"""
import copy
import json
import logging
import os
import random
from typing import Optional

logger = logging.getLogger("culturix.media.ltx25_workflow")

_DEFAULT_WORKFLOW_PATH = os.path.join(
    os.path.dirname(__file__), "workflows", "ltx25_image_to_video.api.json"
)

# The template pins the optional prompt-enhancer CLIP, which we don't ship
# to the volume. Enhancement is disabled anyway, but ComfyUI validates
# every node feeding an output and rejects an unknown filename, so every
# CLIPLoader is pointed at the main encoder.
MAIN_CLIP = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"

# The template's own duration widget value — used to find the node to
# overwrite, since the converted graph has no stable semantic name for it.
_TEMPLATE_DEFAULT_DURATION = 5

DEFAULT_NEGATIVE_PROMPT = (
    "blurry, out of focus, low quality, compression artifacts, ghosting, double exposure, "
    "motion smear, warped face, melted features, changing faces, inconsistent identity, "
    "distorted anatomy, deformed hands, extra limbs, extra fingers, disfigured, "
    # Confirmed live 2026-09-02 on a three-hander: instead of cutting to the
    # third character for her line, the model rendered a DUPLICATE of the
    # second one speaking it. Naming the speaker per shot is the primary fix
    # (build_ltx25_scene_prompt); this discourages the duplication itself.
    "duplicate character, cloned character, twin, repeated face, same person twice, "
    "waxy skin, plastic skin, uncanny, flickering, watermark, text, caption, subtitles"
)

# Output geometry of the converted template. The reference anchor is
# pre-sized to this by the caller (see build_composite_anchor) because the
# graph's own resize node is removed below.
TARGET_WIDTH = 1280
TARGET_HEIGHT = 704


class LTX25WorkflowError(Exception):
    pass


def load_workflow_template() -> dict:
    path = os.getenv("LTX25_WORKFLOW_PATH") or _DEFAULT_WORKFLOW_PATH
    if not os.path.exists(path):
        raise LTX25WorkflowError(f"LTX-2.5 workflow not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _nodes_of_class(workflow: dict, class_type: str) -> list:
    return [nid for nid, n in workflow.items() if n.get("class_type") == class_type]


def _strip_resize_node(workflow: dict) -> None:
    """Removes ResizeImageMaskNode, rewiring its consumers to its source.

    Its `resize_type` is a COMFY_DYNAMICCOMBO_V3: a
    {"value": ..., "longer_size": ...} dict passes ComfyUI's validator but
    execution then fails with "execute() missing 1 required positional
    argument: 'resize_type'". Confirmed live 2026-09-02.

    Safe to remove: the node only resizes the input image before
    LTXVPreprocess, and callers supply an anchor already at
    TARGET_WIDTH x TARGET_HEIGHT. Nothing in the sampling path changes.
    """
    for node_id in _nodes_of_class(workflow, "ResizeImageMaskNode"):
        source = workflow[node_id]["inputs"].get("input")
        for other in workflow.values():
            for key, value in list(other["inputs"].items()):
                if isinstance(value, list) and len(value) == 2 and str(value[0]) == str(node_id):
                    other["inputs"][key] = source
        del workflow[node_id]


def build_workflow(prompt_text: str, duration_seconds: int,
                   negative_prompt: Optional[str] = None,
                   seed: Optional[int] = None,
                   reference_image_filename: str = "reference.png") -> dict:
    """Returns a submit-ready copy of the LTX-2.5 graph.

    duration_seconds drives the template's own duration input (it derives
    frame count and audio length from it), so shots are NOT looped here the
    way the 2.3 path loops them — 2.5 renders the whole multi-shot scene in
    one generation.
    """
    workflow = copy.deepcopy(load_workflow_template())

    # Positive prompt: the template feeds it through a
    # PrimitiveStringMultiline that the subgraph boundary resolved to a
    # literal string.
    prompt_nodes = [
        nid for nid in _nodes_of_class(workflow, "PrimitiveStringMultiline")
        if isinstance(workflow[nid]["inputs"].get("value"), str)
    ]
    if not prompt_nodes:
        raise LTX25WorkflowError("No literal PrimitiveStringMultiline node to inject the prompt into")
    for node_id in prompt_nodes:
        workflow[node_id]["inputs"]["value"] = prompt_text

    # Negative prompt: the CLIPTextEncode whose text is a literal. The
    # positive one takes its text via a link from the enhancer chain.
    negative_text = DEFAULT_NEGATIVE_PROMPT if negative_prompt is None else negative_prompt
    for node_id in _nodes_of_class(workflow, "CLIPTextEncode"):
        if isinstance(workflow[node_id]["inputs"].get("text"), str):
            workflow[node_id]["inputs"]["text"] = negative_text

    for node_id in _nodes_of_class(workflow, "PrimitiveInt"):
        if workflow[node_id]["inputs"].get("value") == _TEMPLATE_DEFAULT_DURATION:
            workflow[node_id]["inputs"]["value"] = int(duration_seconds)

    # A fresh seed per run, or ComfyUI's execution cache returns a previous
    # result for identical inputs — the same trap the 2.3 path hit.
    for node_id in _nodes_of_class(workflow, "RandomNoise"):
        if isinstance(workflow[node_id]["inputs"].get("noise_seed"), int):
            workflow[node_id]["inputs"]["noise_seed"] = (
                seed if seed is not None else random.randint(1, 2**31 - 1)
            )

    for node_id in _nodes_of_class(workflow, "CLIPLoader"):
        workflow[node_id]["inputs"]["clip_name"] = MAIN_CLIP
    # Keep prompt enhancement off so the substituted enhancer CLIP stays inert.
    for node in workflow.values():
        if node["class_type"] == "PrimitiveBoolean" and isinstance(node["inputs"].get("value"), bool):
            node["inputs"]["value"] = False

    for node_id in _nodes_of_class(workflow, "LoadImage"):
        workflow[node_id]["inputs"]["image"] = reference_image_filename

    _strip_resize_node(workflow)

    # SaveVideo's format/codec are widget slots the UI->API converter's
    # schema walk doesn't surface; without them execution reaches the very
    # last node and dies on a missing positional argument.
    for node_id in _nodes_of_class(workflow, "SaveVideo"):
        workflow[node_id]["inputs"].setdefault("format", "auto")
        workflow[node_id]["inputs"].setdefault("codec", "auto")

    return workflow


def build_composite_anchor(image_bytes_list: list) -> bytes:
    """Composites every cast member's portrait into ONE first frame.

    Image conditioning propagates whatever the first frame contains, so
    every identity that must persist has to appear in it — a single
    portrait can only ever carry one face. Slots run left to right so the
    model's spatial reading of the frame agrees with the blocking named in
    the prompt.

    Returns PNG bytes at TARGET_WIDTH x TARGET_HEIGHT.
    """
    from io import BytesIO
    from PIL import Image

    usable = [b for b in image_bytes_list if b]
    if not usable:
        raise LTX25WorkflowError("No character images available to build a composite anchor")

    canvas = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (28, 24, 22))
    slot_width = TARGET_WIDTH // len(usable)
    for index, raw in enumerate(usable):
        image = Image.open(BytesIO(raw)).convert("RGB")
        # Cover-fit into the slot, cropping rather than stretching so faces
        # keep their proportions.
        scale = max(slot_width / image.width, TARGET_HEIGHT / image.height)
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))))
        left = (image.width - slot_width) // 2
        top = (image.height - TARGET_HEIGHT) // 2
        canvas.paste(image.crop((left, top, left + slot_width, top + TARGET_HEIGHT)), (index * slot_width, 0))

    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()

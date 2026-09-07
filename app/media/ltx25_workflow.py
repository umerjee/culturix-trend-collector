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
# Resolution the background matte is computed at — see _matte_background.
_MATTE_RESOLUTION = 256
# Flood-fill tolerance. PIL compares against the SEED pixel using the SUM of
# the per-channel differences, not a per-channel margin — so this number is
# roughly three times what it looks like. At 40 the fill could not cross a
# studio sweep shading from 235 to 253 (a sum-diff of ~50) and Blix came
# through on a white rectangle. Measured across the live cast, coverage is
# flat from 80 upward, so 100 sits on the plateau rather than at its edge.
_MATTE_TOLERANCE = 100

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
                   reference_image_filename: str = "reference.png",
                   video_cfg: Optional[float] = None,
                   audio_cfg: Optional[float] = None,
                   image_strength: Optional[float] = None) -> dict:
    """Returns a submit-ready copy of the LTX-2.5 graph.

    duration_seconds drives the template's own duration input (it derives
    frame count and audio length from it), so shots are NOT looped here the
    way the 2.3 path loops them — 2.5 renders the whole multi-shot scene in
    one generation.

    video_cfg/audio_cfg/image_strength are EXPERIMENTAL overrides, left at
    the official template's own defaults (both CFGs at 1, i.e. effectively
    no classifier-free guidance; image-conditioning strength at 0.7 for the
    base pass) when not given. Added 2026-09-03 to investigate a live
    finding: two of three composite-anchor face regions never left their
    static portrait-crop framing for an ENTIRE 33s render regardless of
    prompt wording (four separate rounds of prompt changes had no effect on
    this specific symptom) — CFG≈1 gives the text prompt very little power
    to steer the output at all, which would explain that. UNVALIDATED:
    distilled models are frequently trained specifically around CFG≈1, so
    raising it, or lowering the image-conditioning strength, could degrade
    output a different way instead of fixing this. See docs/culturix-video-
    pipeline.md section 2 for the full investigation."""
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

    # See this function's own docstring — experimental, unvalidated overrides.
    if video_cfg is not None or audio_cfg is not None:
        for node_id in _nodes_of_class(workflow, "LTXVDualCFGGuider"):
            if video_cfg is not None:
                workflow[node_id]["inputs"]["video_cfg"] = video_cfg
            if audio_cfg is not None:
                workflow[node_id]["inputs"]["audio_cfg"] = audio_cfg
    if image_strength is not None:
        # Only the BASE pass (strength 0.7 in the official template) governs
        # initial adherence to the reference image — matched by value, same
        # convention this function already uses for the duration widget,
        # since node ids aren't a stable way to address the template. The
        # upscale pass's strength=1 is a different, later commit step and is
        # deliberately left alone.
        for node_id in _nodes_of_class(workflow, "LTXVImgToVideoInplace"):
            if workflow[node_id]["inputs"].get("strength") == 0.7:
                workflow[node_id]["inputs"]["strength"] = image_strength

    return workflow


def _matte_background(image, tolerance: int = _MATTE_TOLERANCE):
    """Returns a mask of the portrait's own studio backdrop.

    Character portraits are generated on a near-white studio background
    (confirmed 2026-09-02: all three of a live cast measured ~235-249 in
    every corner, RGB with no alpha). The composite anchor IS the video's
    first frame, so pasting those portraits unchanged opened the video on a
    white sheet no matter what the prompt said the setting was.

    Flood-filled from the four corners rather than thresholding on
    brightness, so a white collar, a highlight or a pale face is kept — only
    background CONNECTED to the frame edge is removed. Returns a mask where
    255 marks the character.
    """
    from PIL import Image, ImageDraw

    # ImageDraw.floodfill is pure Python, so it is filled on a thumbnail and
    # the mask scaled back up — at full 1024x1024 a single portrait took
    # minutes. Bilinear upscaling also feathers the edge, which composites
    # more naturally than a hard cut.
    sentinel = (255, 0, 255)
    probe = image.convert("RGB").copy()
    probe.thumbnail((_MATTE_RESOLUTION, _MATTE_RESOLUTION))
    width, height = probe.size
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        ImageDraw.floodfill(probe, corner, sentinel, thresh=tolerance)

    # Anything the fill did NOT reach is the subject.
    mask = Image.new("L", probe.size, 255)
    mask.putdata([0 if px == sentinel else 255 for px in probe.getdata()])

    # Only catches a matte that removed essentially EVERYTHING — cutting the
    # character out entirely is worse than leaving their backdrop in. The
    # bar was 10% and wrongly rejected a good matte: a character framed small
    # in a large studio sweep legitimately keeps only a few percent of the
    # portrait, and Blix came through on a white rectangle because of it.
    kept = sum(mask.getdata()) / (255 * width * height)
    if kept < 0.02:
        logger.warning("Matte kept only %.0f%% of the portrait — leaving it unmatted", kept * 100)
        return Image.new("L", image.size, 255)

    resized = mask.resize(image.size, Image.BILINEAR)
    # BILINEAR smooths the VALUES at the edge but not its SHAPE — the
    # boundary is still the coarse, blocky contour of a _MATTE_RESOLUTION-px
    # grid, just stretched up. Confirmed live 2026-09-03: this reads as a
    # dotted/pixelated outline tracing every character's silhouette in the
    # final render (reported on Hans, Carlos AND Aisha — every anchor, not
    # one bad portrait). A Gaussian blur on the already-upscaled mask smooths
    # that staircase directly, cheap (no per-pixel Python loop, unlike the
    # flood-fill above) regardless of _MATTE_RESOLUTION. Radius scales with
    # the upscale factor so it's roughly one low-res grid cell wide at full
    # resolution — enough to erase the staircase without eating real detail
    # (a stray hair, a collar point) into a visible halo.
    from PIL import ImageFilter
    upscale_factor = image.size[0] / width
    blur_radius = max(2, round(upscale_factor / 2))
    return resized.filter(ImageFilter.GaussianBlur(radius=blur_radius))


def _paint_backdrop_canvas(backdrop_bytes: Optional[bytes]):
    """A TARGET_WIDTH x TARGET_HEIGHT canvas showing the Location's own art
    (cover-fit and centered), or a dark neutral if there's none — shared by
    build_composite_anchor and build_backdrop_only_anchor so a subject-only
    segment's empty-of-people frame still matches the same backdrop the
    cast's own anchor uses, not a different-looking fallback."""
    from io import BytesIO
    from PIL import Image

    canvas = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (28, 24, 22))
    if backdrop_bytes:
        backdrop = Image.open(BytesIO(backdrop_bytes)).convert("RGB")
        scale = max(TARGET_WIDTH / backdrop.width, TARGET_HEIGHT / backdrop.height)
        backdrop = backdrop.resize(
            (max(1, round(backdrop.width * scale)), max(1, round(backdrop.height * scale)))
        )
        left = (backdrop.width - TARGET_WIDTH) // 2
        top = (backdrop.height - TARGET_HEIGHT) // 2
        canvas.paste(backdrop.crop((left, top, left + TARGET_WIDTH, top + TARGET_HEIGHT)), (0, 0))
    return canvas


def build_backdrop_only_anchor(backdrop_bytes: Optional[bytes] = None) -> bytes:
    """A reference frame with NO character face in it at all — for a
    segment whose shots are all shot_focus "subject" (nobody on screen,
    e.g. explaining a solar eclipse with the eclipse itself, not the
    narrator, filling the frame). Confirmed live 2026-09-07: chaining such
    a segment off the previous segment's last frame (a character's own
    close-up) kept that face dominant through the ENTIRE subject shot —
    the eclipse itself only appeared as a small background element in the
    last second. A face-free anchor removes the thing the model was
    holding onto instead of asking it to let go via text, which this
    model has already been confirmed not to reliably do (see docs/culturix-
    video-pipeline.md's CFG/strength experiments — text has very little
    steering power here).

    Returns PNG bytes at TARGET_WIDTH x TARGET_HEIGHT.
    """
    from io import BytesIO

    canvas = _paint_backdrop_canvas(backdrop_bytes)
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def build_composite_anchor(image_bytes_list: list, backdrop_bytes: Optional[bytes] = None) -> bytes:
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

    canvas = _paint_backdrop_canvas(backdrop_bytes)

    slot_width = TARGET_WIDTH // len(usable)
    for index, raw in enumerate(usable):
        image = Image.open(BytesIO(raw)).convert("RGB")
        mask = _matte_background(image)
        # Cover-fit into the slot, cropping rather than stretching so faces
        # keep their proportions. The mask is transformed identically, or the
        # cut-out would drift off the character.
        scale = max(slot_width / image.width, TARGET_HEIGHT / image.height)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(size)
        mask = mask.resize(size)
        left = (image.width - slot_width) // 2
        top = (image.height - TARGET_HEIGHT) // 2
        box = (left, top, left + slot_width, top + TARGET_HEIGHT)
        canvas.paste(image.crop(box), (index * slot_width, 0), mask.crop(box))

    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()

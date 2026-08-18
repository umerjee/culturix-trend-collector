# `ltx_text_to_video.json` — status: partially verified

This is a simplified, hand-built ComfyUI API-format workflow for LTX-2.3
text-to-video generation — not a copy of Lightricks/Comfy's own official
"LTX-2.3: Text to Video" template (that one is a ~44-node composite graph
with native audio, dual text-encoding paths, distillation LoRAs, and
upscaling — overkill for what this pipeline needs). This file intentionally
stays single-stage: checkpoint → prompt encode → character LoRA → sample →
decode → save.

**What's now confirmed** (live RunPod validation, 2026-08-18 — a real
end-to-end generation against the *official* template, not this file
directly, but enough of its node graph was inspected to correct the
assumptions below):

- `ckpt_name` — the real downloaded checkpoint (from `Lightricks/LTX-2.3-fp8`,
  file `ltx-2.3-22b-dev.safetensors`) shows up in ComfyUI's own dropdown as
  `ltx-2.3-22b-dev.safetensors` (no `-fp8` suffix in the visible name, despite
  being the fp8-quantized file) — node `1` uses this exact string now. If you
  re-download and it lands under a different name, update this field.
- `EmptyLTXVLatentVideo` — class_type confirmed correct; its 3rd widget/input
  is `length` and is genuinely in **frames**, not seconds (confirmed via the
  real template's widget order: `[width, height, length, batch_size]`).
- `width`/`height` — set to `720`/`1280` (vertical 9:16, for TikTok/Reels/
  Shorts) — confirmed via the official template after manually overriding
  its own landscape default (`1280x720`).
- fps — kept at `24` (unchanged). The real template turned out to have
  **three different fps-shaped numbers** that are NOT the same knob: a node
  literally titled "fps" defaults to `24`, a `CreateVideo` mux node is
  hardcoded to `30`, and an audio-latent node uses `25` for its own timing.
  `24` is the one that actually lines up with `EmptyLTXVLatentVideo`'s frame
  count (what `ltx_workflow.py` injects into), so that's what this file and
  `SaveVideo`'s `fps` both use — don't assume a single universal fps value
  if you rebuild this from the official template instead.
- LoRA node — changed from a plain `LoraLoader` to **`LoraLoaderModelOnly`**
  (node `5`). Confirmed via the official template: its own distillation LoRA
  uses `LoraLoaderModelOnly`, which only touches `model` (no `clip` output),
  so downstream `CLIPTextEncode` nodes now correctly read `clip` straight
  from the checkpoint loader (node `1`) instead of from the LoRA node.
  **Caveat**: the official template actually uses `LoraLoaderModelOnly` for
  its distillation speed-LoRA, not a character-identity slot — it has no
  such slot at all (character consistency there comes from image
  conditioning, not a trained LoRA). This file's node `5` is a slot we
  added ourselves for the character LoRA `culturetoon_lora.py` trains; keep
  exactly one `LoraLoaderModelOnly` node in this file for
  `ltx_workflow.py`'s injection to stay unambiguous — see that module's own
  header comment.
- Seed — **not** set via this file's `KSampler.seed` by `ltx_workflow.py`
  anymore exclusively; the real official template puts seed on a
  `RandomNoise` node (input key `noise_seed`) instead, feeding a
  `SamplerCustomAdvanced` rather than a plain `KSampler`. `ltx_workflow.py`
  now tries `RandomNoise` first and falls back to plain `KSampler.seed` (what
  this file still uses, since a generic `KSampler` is valid ComfyUI and
  simpler for a single-stage workflow) — so this file works either way.
- Prompt node selection — the official template's positive AND negative
  `CLIPTextEncode` nodes both ship with **non-empty** placeholder text, so
  the old "inject into whichever node has empty text" heuristic would
  silently pick neither on that template. `ltx_workflow.py` now prefers each
  node's `_meta.title` (containing "positive", not "negative") when present,
  falling back to the empty-text heuristic otherwise — this file's nodes `2`
  and `3` carry explicit titles for that reason. Keep the titles if you edit
  this file, or keep node `2`'s starting text empty as the fallback signal.

**Still unverified** — this file itself has never been run start-to-finish
against a live ComfyUI instance; only the official Lightricks/Comfy template
was, and the facts above were cross-checked against that run's node graph.
Before the first real automated batch:

1. Confirm this exact file loads and runs cleanly in ComfyUI (Load → open
   this JSON, or submit it via `comfyui_client.py` against a manually
   started Pod) — not just that its individual node types/fields are right
   in isolation.
2. `KSampler` settings (`steps`/`cfg`/`sampler_name`/`scheduler`) are generic
   starting points, not tuned for LTX-2.3 specifically — the official
   template uses a materially different, more complex sampling chain
   (`RandomNoise` → `KSamplerSelect` → `CFGGuider`/`GuiderParameters` →
   `SamplerCustomAdvanced`) that may produce meaningfully better output;
   worth A/B-ing against this simpler `KSampler` path once you have a
   baseline.
3. `SaveVideo` (node `8`) — confirm it emits an entry under
   `outputs[node_id].videos` (or `.gifs`) in `/history/{prompt_id}` —
   `app/media/comfyui_client.py`'s `download_output()` looks for
   `gifs`/`videos`/`images` keys in that order.

**Dependency fixes needed on any fresh ComfyUI image/build** (hit live
during validation, not obvious from the template itself):

- `ComfyUI-LTXVideo`'s `__init__.py` fails to import entirely on a stock
  install (`ImportError: cannot import name 'pad' from
  'kornia.geometry.transform.pyramid'`, from its own `pyramid_blending`
  module) — this takes down *every* LTXV node type, not just blending, and
  shows up in ComfyUI as every LTXV loader dropdown being empty /
  "unsupported nodes" on the whole graph. Fix: comment out the
  `pyramid_blending` import and its usage in `ComfyUI-LTXVideo/__init__.py`
  (Laplacian-pyramid blending isn't needed for basic text-to-video). This is
  a genuine kornia/LTXVideo incompatibility, not a version-lag issue —
  upgrading kornia does not fix it (0.8.3 was already latest at time of
  testing).
- `comfy_kitchen` needs upgrading past its default-installed version for
  fp8/fp4 model support (`cannot import name
  'TensorCoreConvRotW4A4Layout'` otherwise) — `pip install --upgrade
  comfy-kitchen` (tested: 0.2.10 → 0.2.31 fixed it; unlike kornia, this one
  actually was just outdated).
- Confirmed real download sources (blob URLs from HuggingFace silently
  download an HTML preview page instead of the model — always convert
  `/blob/main/` → `/resolve/main/` before downloading):
  - Checkpoint: `Lightricks/LTX-2.3-fp8`, file `ltx-2.3-22b-dev-fp8.safetensors`
    (lands in ComfyUI's own listing as `ltx-2.3-22b-dev.safetensors`).
  - Distilled LoRA (used by the official template's own speed-LoRA slot,
    not needed by this file's character-LoRA slot): `Comfy-Org/ltx-2.3`,
    path `split_files/loras/...`.
  - Text encoder: `Comfy-Org/ltx-2`, path
    `split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors`.
  - Upscaler (not used by this file — only relevant if you adopt the
    official template's multi-stage graph): `Lightricks/LTX-2.3`, file
    `ltx-2.3-spatial-upscaler-x2-1.1.safetensors`.
  - Deliberately excluded: an "abliterated" (safety-training-stripped)
    Gemma LoRA that shows up as an optional download in the official
    template's Missing Models panel — not downloaded and not referenced by
    this file, on the same values/safety basis as CultureToons' existing
    cultural-sensitivity guardrails elsewhere in the product.

## If you rebuild this from scratch in the ComfyUI GUI instead

Design the graph, then **Save (API Format)** and drop the resulting JSON in
here (or point `LTX_WORKFLOW_PATH` at wherever you save it). `ltx_workflow.py`
injects by matching each node's `class_type`, not hardcoded node IDs, so a
differently-numbered graph works as long as it has: a `CLIPTextEncode` node
identifiable as positive (via `_meta.title` containing "positive", or empty
starting text if untitled); exactly one `LoraLoaderModelOnly` node if you
want character-LoRA support; and, for duration injection, exactly one
`EmptyLTXVLatentVideo` node.

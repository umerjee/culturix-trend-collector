# `ltx_text_to_video.json` — status: UNVERIFIED

This is a best-effort default ComfyUI API-format workflow for LTX-2
text-to-video generation, built from general knowledge of the
`ComfyUI-LTXVideo` custom node set (`LoraLoader`, `EmptyLTXVLatentVideo`,
standard `CLIPTextEncode`/`KSampler`/`VAEDecode`). **It has not been run
against a live ComfyUI instance** — there is no GPU/ComfyUI access available
to verify it, so treat every detail below as a hypothesis, not a fact.

## Before the first real batch run, open this in a live ComfyUI + LTX-2
install and check, in order:

1. **`ckpt_name` (node `1`)** — must match whatever filename the LTX-2 FP8
   checkpoint actually downloaded as into `ComfyUI/models/checkpoints/`.
2. **`EmptyLTXVLatentVideo` (node `4`)** — confirm this is the real class
   name for LTX's empty-latent-video node in your installed version of
   `ComfyUI-LTXVideo`, and that `length` is genuinely in frames (not
   seconds) and `width`/`height` match what the model expects for vertical
   9:16 output. `app/media/ltx_workflow.py`'s duration injection silently
   no-ops (doesn't error) if this class name is wrong — check the logs for
   a "no {node} found" warning if durations don't seem to be applying.
3. **`LoraLoader` (node `5`)** — confirm a plain `LoraLoader` (as opposed to
   an LTX-specific LoRA node) is actually compatible with LTX-2's model
   architecture; some video models need a dedicated LoRA loader node.
4. **`KSampler` settings (node `6`)** — `steps`/`cfg`/`sampler_name`/
   `scheduler` are generic starting points, not tuned for LTX-2 specifically.
5. **`SaveVideo` (node `8`)** — confirm this node type exists in your
   ComfyUI version and actually emits an entry under `outputs[node_id].videos`
   (or `.gifs`) in `/history/{prompt_id}` — `app/media/comfyui_client.py`'s
   `download_output()` looks for `gifs`/`videos`/`images` keys in that order.

## If you rebuild this from scratch in the ComfyUI GUI instead

Design the graph, then **Save (API Format)** and drop the resulting JSON in
here (or point `LTX_WORKFLOW_PATH` at wherever you save it). `ltx_workflow.py`
injects by matching each node's `class_type`, not hardcoded node IDs, so a
differently-numbered graph works as long as it still has one
`CLIPTextEncode` node with empty starting text (for the positive prompt —
see the injection logic's own comment on how it picks the positive node
over a negative one) and, if you want LoRA support, one `LoraLoader` node.

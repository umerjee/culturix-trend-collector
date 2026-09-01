# LTX-2.5 — official ComfyUI workflow templates

These two files are **unmodified** official templates, fetched from
`Comfy-Org/workflow_templates` (`templates/video_ltx2_5_i2v.json`,
`templates/video_ltx2_5_t2v.json`) on 2026-09-01:

- `video_ltx2_5_i2v.json` — image-to-video. The one that matches Culturix's
  use case (a character's photo anchors the shot).
- `video_ltx2_5_t2v.json` — text-to-video, kept for reference.

They are checked in deliberately **as-is**, rather than hand-simplified.
The LTX-2.3 workflow this replaces (`../ltx_text_to_video.json`) was
hand-built down to ~10 nodes from a ~44-node official template, and that
simplification is exactly what silently dropped the `LTXVConditioning`
node — the model then received no frame-rate signal at all and real
output came back as near-static held poses ("a collection of images")
rather than animation. Don't repeat that: start from these and remove
only what you can prove is unused.

## Why LTX-2.5 rather than staying on 2.3

Verified against the real graph in `video_ltx2_5_i2v.json`, not assumed:

- **Native synchronized audio.** `LTXVEmptyLatentAudio` →
  `LTXVConcatAVLatent` → sampled jointly with the video latent →
  `LTXVSeparateAVLatent` → `LTXVAudioVAEDecode`. Audio and video are
  denoised *together in one pass*. The 2.3 pipeline instead synthesized
  narration separately (Chatterbox TTS) and muxed it on with ffmpeg
  afterwards, which structurally cannot lip-sync — the video knows
  nothing about the audio and vice versa. This is the root cause of
  "the voice and image don't match".
- **Native multishot.** Per Lightricks' release notes, one generation
  produces multiple connected shots holding character, environment,
  lighting and voice across cuts. That replaces the last-frame chaining
  workaround added to `culturetoon_selfhosted_video.py` on 2026-09-01,
  which approximated continuity by feeding each shot's final frame into
  the next.
- **Two-stage latent upscaling** via `LTXVLatentUpsampler` +
  `LatentUpscaleModelLoader`, and tiled decode via `VAEDecodeTiled`.

## Model files to download onto the Network Volume

Exact filenames are read out of the template's own loader widgets, so
they match what the graph will actually ask ComfyUI for. Paths are
relative to the volume's `ComfyUI/` prefix (see `../README.md` and
`deploy/runpod_serverless/extra_model_paths.yaml` for why that prefix
exists).

| File | Target folder | Loader node |
|---|---|---|
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `models/diffusion_models/` | `UNETLoader` |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `models/text_encoders/` | `CLIPLoader` |
| `gemma4_e2b_it_int8_convrot.safetensors` | `models/text_encoders/` | `CLIPLoader` (prompt enhancer) |
| `ltx-2.5-video-vae-bf16.safetensors` | `models/vae/` | `VAELoader` |
| `ltx-2.5-audio-vae-bf16.safetensors` | `models/vae/` | `VAELoader` |
| `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | `models/latent_upscale_models/` | `LatentUpscaleModelLoader` |

Notes that will bite otherwise:

- **The transformer loads via `UNETLoader`, not `CheckpointLoaderSimple`**,
  and lives in `models/diffusion_models/` — a different node *and* a
  different folder from the 2.3 setup. `extra_model_paths.yaml` already
  maps `diffusion_models` and `text_encoders`, but **not**
  `latent_upscale_models`; that mapping has to be added or the upscaler
  will not appear in ComfyUI's dropdown.
- **Gemma-4, not Gemma-3.** The 2.3 workflow loads
  `gemma-3-12b-it-qat-q4_0-unquantized`. LTX-2.5 requires its own
  fine-tuned `gemma4-12b-with-proj-ltx-2.5` build, and the pipeline
  validates the encoder version against what the checkpoint was trained
  with — Google's stock Gemma 4 is explicitly not a substitute.
- The templates above pin the **distilled int8** transformer (fast). The
  BF16 base (`ltx-2.5-22b-dev-transformer-bf16.safetensors`) is higher
  quality and slower; switching means changing the `UNETLoader` widget
  and re-checking VRAM headroom.

## Known blocker before this can be wired in

These templates are in ComfyUI's **UI format** (`nodes` + `links` +
`definitions.subgraphs`). Our worker submits **API format** (a flat
`{node_id: {class_type, inputs}}` dict) to ComfyUI's `/prompt`, which is
what `app/media/ltx_workflow.py` builds and manipulates.

Converting UI → API requires each node's real input *names*, because the
UI format stores widget values positionally (`widgets_values`) with no
names attached. That mapping comes from a running ComfyUI's
`/object_info` endpoint — it cannot be reliably inferred by hand, and
guessing it is how you end up with another silently-wrong graph.

Two supported ways to produce the API-format file:

1. Open the template in a ComfyUI instance that has the LTX-2.5 nodes and
   the models above, then **Workflow → Export (API)**. This is what the
   2.3 README already recommends.
2. Point `scripts/convert_comfy_workflow.py` (see that script) at a
   running ComfyUI's `/object_info` to do the conversion programmatically
   — the RunPod worker already runs ComfyUI on `127.0.0.1:8188`, so this
   can be done there without any extra infrastructure.

## LoRA compatibility — this is the expensive part

Character LoRAs trained against the LTX-2.3 22B transformer **will not
load** on the 2.5 transformer: adapter tensors are shaped to the specific
base architecture. Every trained character (Hans, Kumar, Wen, and Aisha
once her corrupt source file is regenerated) needs retraining against
LTX-2.5 before the self-hosted path produces recognisable characters
again. Budget that as real GPU time, not a config change.

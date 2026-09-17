# CultureToons self-hosted video — setup

**This file previously walked through setting up LTX-2.3 plus per-character
LoRA training. That whole path — `deploy/runpod_training/`,
`app/services/culturetoon_lora.py`, the `lora_*` character-variant
columns/UI, and the LTX-2.3 rendering code — was removed on 2026-09-17.**
Self-hosted video is LTX-2.5 only now; identity comes from image
conditioning (a portrait per character), not a trained model.

For the current setup and operations, see:

- **`docs/culturix-video-pipeline.md`** — architecture, required env vars,
  the model files that need to be on the Network Volume, the workflow
  graph, and the recurring-failure-patterns list worth reading before
  touching this path.
- **`deploy/runpod_serverless/README.md`** and
  **`deploy/runpod_serverless/Dockerfile`** — the Serverless inference
  worker (ComfyUI + LTX-2.5 + MSR custom nodes), built automatically by
  `.github/workflows/build-ltx-serverless-image.yml` on every push that
  touches that folder.
- **`scripts/download_ltx25_to_volume.sh`** — populates a Network Volume
  with the LTX-2.5 model files, in the exact folders the workflow's loader
  nodes expect.
- **`app/media/runpod_volume_relay.py`** — how to reach a Network Volume
  that has no S3-compatible API of its own (a short-lived CPU carrier pod
  over SSH), for anything that needs a one-off read/write to the volume
  outside the normal inference/build flow.

If you're setting this up from scratch, `docs/culturix-video-pipeline.md`
§3 ("Environment variables") and §4 ("Models on the volume") are the
fastest way to see exactly what needs to exist before the Serverless
endpoint will work.

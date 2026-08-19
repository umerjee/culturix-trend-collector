# CultureToons self-hosted video — LoRA training pod image

Builds `RUNPOD_TRAINING_IMAGE`: the container `create_training_pod()`
(`app/media/runpod_client.py`) deploys fresh, on demand, for each
character's LoRA training run (`app/services/culturetoon_lora.py`). Unlike
`deploy/runpod_serverless/` (a Serverless endpoint, driven over HTTP), this
is a regular Pod driven entirely over SSH — see the Dockerfile's own header
comment for exactly why `runpod/pytorch` is the base instead of
`runpod/worker-comfyui`.

## 1. Build and push the image

Needs Docker and a container registry you can push to (Docker Hub is
simplest — RunPod pulls from any public registry):

```bash
cd deploy/runpod_training
docker build -t <your-dockerhub-username>/culturix-ltx-training:latest .
docker push <your-dockerhub-username>/culturix-ltx-training:latest
```

This pulls a fairly large CUDA devel base image and clones LTX-2 on top of
it — expect the first build to take a while.

## 2. Set the env vars (Railway)

Unlike the Serverless endpoint, there's no separate "deploy" step in the
RunPod console for this one — Pods are created on demand directly from the
image name, so once it's pushed you just need:

- `RUNPOD_TRAINING_IMAGE` — `<your-dockerhub-username>/culturix-ltx-training:latest`
  (exactly what you pushed above).
- `RUNPOD_TRAINING_GPU_TYPE_ID` — the literal string `NVIDIA A100 80GB PCIe`
  (PCIe specifically, not SXM — see `runpod_client.py`'s own docstring on
  why). Not something you look up; the code expects this exact string.
- `RUNPOD_SSH_PRIVATE_KEY` — see the main setup guide; the matching public
  key needs to be added in RunPod console → Settings → SSH Public Keys
  first, or pods built from this image won't actually accept a connection
  from it.
- `HF_TOKEN` — **new requirement found while building this image**:
  `google/gemma-3-12b-it` (the default training text encoder) is a gated
  HuggingFace model. `hf download` for it will fail with an authentication
  error unless this is set to a token from an account that has accepted
  Gemma's license on huggingface.co (Settings → Access Tokens, on the
  account that clicked "Agree" on the Gemma model page). Only the text
  encoder download needs this — the LTX checkpoint repo is public.
- `RUNPOD_API_KEY` — same key as everywhere else, if not already set.

## 3. Validate before trusting the automated `/train-lora` endpoint

`app/services/culturetoon_lora.py`'s own module docstring already flags
two real open questions this image can't resolve on its own — worth a
manual first run before pointing it at a real character:

1. Whether ltx-trainer's `video` dataset field genuinely accepts a
   looped-still-image workaround (what `train_character_lora()` does), or
   needs an actual short video per training image.
2. Whether `Lightricks/LTX-2.3` / `google/gemma-3-12b-it` are really the
   right checkpoint/text-encoder sources for *training* specifically (as
   opposed to the confirmed-correct fp8 *inference* checkpoint) —
   overridable via `LTX_TRAINING_CHECKPOINT_REPO`/`_FILE`/
   `LTX_TRAINING_TEXT_ENCODER_REPO` if not.

Trigger one real run via the app itself once a character variant has 10+
Expression images (`POST /variants/{id}/train-lora`, or the "Start
training" button in the Characters tab), then check `lora_status` reaches
`"ready"` and `lora_error` (if it instead reaches `"failed"`) for exactly
which of the above assumptions broke first.

## Notes / open questions to resolve during that first real run

- This Dockerfile's dependency install (last `RUN` in the Dockerfile) is
  best-effort — it wasn't possible to confirm ltx-trainer's exact
  requirements file(s) from outside a real build/run. If the first
  training attempt fails with an `ImportError` rather than one of the two
  numbered questions above, that's this step under-covering something —
  add the missing package to the Dockerfile and rebuild.
- Training wall-clock time on a fresh A100 is unknown — `_TRAINING_TIMEOUT_SECONDS`
  in `culturetoon_lora.py` gives it up to an hour; tighten or loosen once
  a real run gives an actual number.
- This pod does not mount the Network Volume (region-availability reasons,
  see `culturetoon_lora.py`'s module docstring) — it downloads its own
  copy of the checkpoint/text encoder every run, which is real time/disk
  cost on top of GPU-hours, worth watching once real numbers exist.

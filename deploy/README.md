# CultureToons self-hosted video — full RunPod setup runbook

Ties together `deploy/runpod_serverless/` (inference) and
`deploy/runpod_training/` (LoRA training) into one ordered walkthrough,
plus the one step neither of those covers on its own: creating and
populating the Network Volume both of them depend on.

Do these in order — later steps assume earlier ones are done.

## Prerequisites

- Docker installed locally (for building the two images).
- A container registry you can push to — Docker Hub is simplest, and
  RunPod pulls from any public registry with no extra config.
- A RunPod account with billing set up (console.runpod.io).
- A HuggingFace account (huggingface.co) — needed twice below: once to
  download models onto the volume, once for the gated Gemma text encoder.

## 1. `RUNPOD_API_KEY`

RunPod console → **Settings** → **API Keys** → Create API Key. Copy it
immediately — RunPod only shows it once. Set as `RUNPOD_API_KEY` in
Railway; it's reused for every RunPod API call this app makes (pod
lifecycle, Serverless job submission).

## 2. Create the Network Volume

RunPod console → **Storage** → **Network Volumes** → **New Network
Volume**.

- **Datacenter/region**: pick one and note it down — the Serverless
  endpoint (step 4) needs GPU stock available in this same region to
  attach it.
- **Size**: 100GB+. The LTX-2 checkpoint and Gemma text encoder together
  run several GB, and every trained character's LoRA adds more.
- **Name**: anything memorable — `culturix` is what these docs assume.

## 3. Populate the volume with the LTX-2 model files

Deploy a temporary Pod (any GPU tier — this step barely uses compute)
with the volume from step 2 attached:

1. Console → **Pods** → **Deploy** → pick any GPU → under **Network
   Volume**, select the volume you just created (only shows up if the
   pod's region matches the volume's region) → Deploy.
2. Open a **Web Terminal** on the running pod (or SSH in).
3. **Confirm where the volume actually mounted** before assuming a path —
   RunPod's own convention for a regular Pod (as opposed to a Serverless
   endpoint, which mounts at `/runpod-volume`) is typically `/workspace`,
   but verify rather than assume: `df -h` and look for a filesystem sized
   to match what you picked in step 2. Whatever that mount path is,
   create the directories under it — the *relative* structure below is
   what matters, since the same underlying volume shows up as
   `/runpod-volume/...` later when the Serverless endpoint mounts it.
4. Download the two required files (exact names/paths confirmed in
   `app/media/workflows/README.md` — always use `/resolve/main/` URLs if
   downloading any other way, `/blob/main/` silently returns an HTML page
   instead of the model):

```bash
pip install -U "huggingface_hub[cli]"

# Adjust MOUNT below to wherever step 3 confirmed the volume lives.
MOUNT=/workspace
mkdir -p "$MOUNT/models/checkpoints" "$MOUNT/models/text_encoders"

hf download Lightricks/LTX-2.3-fp8 ltx-2.3-22b-dev-fp8.safetensors \
    --local-dir "$MOUNT/models/checkpoints"

hf download Comfy-Org/ltx-2 \
    --include "split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors" \
    --local-dir "$MOUNT/models/text_encoders"
```

5. Terminate this temporary pod once both downloads finish — the files
   stay on the volume regardless.

## 4. Build and deploy the Serverless inference worker

```bash
cd deploy/runpod_serverless
docker build -t <your-dockerhub-username>/culturix-ltx-serverless:latest .
docker push <your-dockerhub-username>/culturix-ltx-serverless:latest
```

Then console → **Serverless** → **New Endpoint**:

- **Container Image**: the tag you just pushed.
- **GPU**: RTX 4090 tier (what this image is sized for).
- **Network Volume**: attach the same volume from step 2 (same region
  requirement as the Pod above).
- **Advanced**: confirm the volume mounts at `/runpod-volume` once
  deployed — should be automatic, worth a one-time check rather than an
  assumption.
- Deploy, then copy the **Endpoint ID** from the endpoint's page.

Set that as `RUNPOD_SERVERLESS_ENDPOINT_ID` in Railway.

Full detail/troubleshooting: `deploy/runpod_serverless/README.md`.

## 5. `RUNPOD_TRAINING_GPU_TYPE_ID`

No lookup — set the literal string `NVIDIA A100 80GB PCIe` (PCIe
specifically, not SXM; more broadly available stock). If a real pod
create ever fails on this exact string, check RunPod's current GPU
picker (Pods → Deploy → GPU list) for whether the naming has shifted.

## 6. Build and push the training image

```bash
cd deploy/runpod_training
docker build -t <your-dockerhub-username>/culturix-ltx-training:latest .
docker push <your-dockerhub-username>/culturix-ltx-training:latest
```

Set `RUNPOD_TRAINING_IMAGE` in Railway to that tag. No separate "deploy"
step here (unlike Serverless) — `create_training_pod()` creates a fresh
Pod directly from this image name per training run.

Full detail: `deploy/runpod_training/README.md`.

## 7. SSH keypair → `RUNPOD_SSH_PRIVATE_KEY`

```bash
ssh-keygen -t ed25519 -f ./culturix_runpod_key -N ""
```

This writes `culturix_runpod_key` (private) and `culturix_runpod_key.pub`
(public) in your current directory — don't commit either to git.

1. Copy the contents of `culturix_runpod_key.pub`.
2. Console → **Settings** → **SSH Public Keys** → add it. Without this,
   pods built from the training image won't accept a connection from the
   matching private key at all.
3. Set `RUNPOD_SSH_PRIVATE_KEY` in Railway to the raw contents of
   `culturix_runpod_key` (the private key file) — paste the full PEM text
   as the env var's value. `app/media/runpod_ssh.py` also accepts a
   filesystem path instead, but Railway's containers don't have a stable
   place to keep that file across deploys, so pasting the key content
   directly is the practical choice here.

## 8. `HF_TOKEN`

`google/gemma-3-12b-it` (the training text encoder) is a gated model —
downloading it needs an authenticated, license-accepted token, not just
the repo name.

1. Sign in at huggingface.co, go to
   `https://huggingface.co/google/gemma-3-12b-it`, and accept the license
   (must be logged in to see the accept button).
2. Settings → Access Tokens → New Token (read access is enough) → copy it.
3. Set `HF_TOKEN` in Railway.

## 9. Validate end-to-end before trusting this for real characters

Once every var above is set in Railway and the app has redeployed:

1. Pick a test character variant with a complete Expression set (10+
   images — most already qualify from normal character setup).
2. Characters tab → "Visual identity (self-hosted)" card → **Start
   training**. Watch `lora_status` go `training` → `ready`. If it lands
   on `failed`, the `lora_error` message should point at which step broke
   — check `deploy/runpod_training/README.md`'s "open questions" section
   first, since the two most likely failure points are already flagged
   there.
3. Once ready, generate a video for a Toon using that character (Toons
   tab → Generate video) and confirm the response/toon ends up with
   `video_provider: "self_hosted"`.

Only after that real round-trip succeeds is it worth relying on the
"Compose an episode" batch feature or the longer 30s/60s duration presets
for anything real — those all sit on top of this same chain.

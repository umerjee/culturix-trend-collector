# CultureToons self-hosted video — Serverless endpoint

Builds a custom RunPod Serverless worker image for LTX-2.3 inference. See
`handler.py`'s header comment for why this can't just be the stock
`runpod/worker-comfyui` image (it drops video outputs).

## 1. Build the image

Two ways — pick whichever matches what you have available.

**Option A — RunPod builds it for you from GitHub, no Docker needed
(confirmed working 2026-08-19):** RunPod console → **Serverless** → **New
Endpoint** → **Deploy from a GitHub repository** → select this repo. It
asks for a single **Dockerfile path** field (no separate build-context
field — it builds with the whole repo as context, not just this folder):

```
/deploy/runpod_serverless/Dockerfile
```

That's also why this Dockerfile's `COPY` lines are prefixed with
`deploy/runpod_serverless/` rather than being bare filenames — they're
resolved from the repo root, not from this directory.

**Option B — build locally and push to a registry**, if you have Docker
installed (Docker Hub is simplest — RunPod pulls from any public
registry):

```bash
cd deploy/runpod_serverless
docker build -t <your-dockerhub-username>/culturix-ltx-serverless:latest .
docker push <your-dockerhub-username>/culturix-ltx-serverless:latest
```

Either way, this will take a while the first time — it's cloning
ComfyUI-LTXVideo and installing its (fairly large) dependency set on top
of the base image's own CUDA/PyTorch/ComfyUI layers.

## 2. Deploy the Serverless endpoint (RunPod console)

If you used Option A above, this happens in the same flow — just
continue on to the settings below. If you used Option B:

1. RunPod console → **Serverless** → **New Endpoint** → **Deploy from a
   Docker image**.
2. **Container Image**: `<your-dockerhub-username>/culturix-ltx-serverless:latest`.
3. **GPU**: RTX 4090 (or whatever tier the Network Volume's models were
   downloaded expecting — same tier as the manual validation pod).
4. **Network Volume**: attach the same `culturix` volume the manual
   validation used (Storage → your volume → should now show as
   attachable to a Serverless endpoint, same region requirement as pods).
5. **Advanced** → confirm the volume mounts at `/runpod-volume` (RunPod's
   documented default for Serverless — should be automatic, just confirm
   after first deploy rather than assuming).
6. **Env vars** on the endpoint itself: none required by our handler.py —
   `COMFYUI_STARTUP_TIMEOUT_SECONDS`/`COMFYUI_JOB_TIMEOUT_SECONDS` are
   optional overrides (defaults 120s/600s) if cold starts or generation
   time need more headroom once you see real numbers.
7. Deploy, then copy the endpoint's ID from the console.

## 3. Wire it into Railway

Set on the backend service:

- `RUNPOD_API_KEY` — same key already used for the training-pod lifecycle
  calls (`app/media/runpod_client.py`), if not already set.
- `RUNPOD_SERVERLESS_ENDPOINT_ID` — the ID from step 2.7.
- `ENABLE_SELFHOSTED_VIDEO=true` and `SELFHOSTED_VIDEO_BRAND_IDS` (comma-
  separated brand UUIDs) once ready to let the scheduled batch runner
  (`app/scheduler.py::run_selfhosted_video_batch`, gated behind these two)
  actually start generating for real brands — leave unset/false until
  you've validated a manual job first (next section).

## 4. Validate before trusting the scheduled batch runner

Don't flip `ENABLE_SELFHOSTED_VIDEO` on until one manual job has round-
tripped successfully — RunPod Serverless cold starts, the Network Volume
mount, and our custom handler have never been tested together yet (only
the manual Pod path has been live-validated so far, and that used a
different startup sequence entirely). From a Python shell with
`RUNPOD_API_KEY`/`RUNPOD_SERVERLESS_ENDPOINT_ID` set:

```python
from app.media import ltx_workflow, runpod_serverless_client
import os

workflow = ltx_workflow.build_workflow("a character waves hello", duration_seconds=3)
video_bytes = runpod_serverless_client.run_inference_job(
    os.environ["RUNPOD_SERVERLESS_ENDPOINT_ID"], workflow, timeout_seconds=900,
)
open("test_output.mp4", "wb").write(video_bytes)
```

The first call will be slow (cold start: container pull if the image
changed, ComfyUI startup, model load off the volume) — `timeout_seconds`
above is set generously for that reason. Play `test_output.mp4` and
sanity-check it the same way the manual Pod output was checked.

## Notes / open questions to resolve during that first real run

- Cold-start time is currently unknown — RunPod bills per-second of actual
  execution, but a slow cold start still affects the batch runner's own
  wall-clock time budget (`SELFHOSTED_BATCH_MAX_MINUTES`) if every job in
  a window hits a cold worker. Worth checking RunPod's console for
  "Active Workers ≥ 1" (keeps one warm) if cold starts prove painful,
  trading idle cost for latency.
- `docker version` inside the existing validation Pod hasn't been
  confirmed — if Docker-in-Docker isn't available there, build from a
  regular machine instead; nothing in this Dockerfile needs to run *on*
  RunPod, only the resulting image needs to end up in a registry RunPod
  can pull from.

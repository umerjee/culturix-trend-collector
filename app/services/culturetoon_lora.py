"""Per-CharacterVariant LoRA training for the self-hosted (RunPod+ComfyUI+
LTX-2) video path's character-consistency mechanism — see
CharacterVariant.lora_path's docstring and
app/services/culturetoon_selfhosted_video.py.

Runs against an EPHEMERAL, on-demand training pod (A100 80GB PCIe — LTX-2's
training path needs bf16/more VRAM than the 4090-class inference tier
comfortably provides), created fresh per run and fully terminated when
done — not a fixed, standing pod.

The training pod does NOT mount the Network Volume — A100 PCIe training
capacity and RTX 4090 inference capacity frequently aren't available in
the same RunPod region (SXM-class cards live in separate NVLink/HGX
chassis from standard PCIe racks, and even PCIe A100 stock doesn't
reliably co-locate with 4090 stock), so there's no guarantee a training
pod can be deployed anywhere the volume is mountable. Instead: ltx-trainer
writes its output to the pod's own local container disk, this module
SFTP-downloads the resulting file back to our backend
(app/media/runpod_ssh.py::download_file), then pushes it to the Network
Volume via its S3-compatible API (app/media/runpod_s3.py) — a network
call, not a filesystem write, so it works regardless of region. Doing the
push from our backend rather than the pod itself also means the S3
credentials never touch the ephemeral, less-trusted remote machine.
lora_path still ends up as a bare filename (not a URL) — see
CharacterVariant.lora_path's docstring — since the file's *final* location
is the volume, this SFTP hop is just how it gets there.

Manual-to-*start* (a human calls POST /variants/{id}/train-lora when they
want a new character trained) but fully automated once started via SSH
(app/media/runpod_ssh.py) — no separate script to run by hand on the pod.

Training DATA is not manual, though — curate_training_images() decides
what goes in automatically, from the variant's own already-generated
Expression images (deterministically captioned from each Expression's own
`name`) plus its canonical portrait, not from a user-sourced upload.
add_training_images()/POST /variants/{id}/lora-training-images still
exists for supplemental extras but is no longer the primary path to
MIN_LORA_TRAINING_IMAGES — most variants reach it purely by having a
complete Expression set, which is already a normal part of character
setup.

ltx-trainer's real CLI (confirmed against Lightricks/LTX-2's own docs,
2026-08-18 — this replaces an earlier version of this file that guessed at
a single `python -m ltx_trainer.train --images_dir ... --output ...`
invocation, which is NOT the real interface) is two stages:

  1. `python scripts/process_dataset.py dataset.json --resolution-buckets
     <WxHxF> --model-path <checkpoint> --text-encoder-path <gemma dir>`
     — dataset.json is a JSON array of `{"caption": ..., "video": <path>}`
     objects (one entry per training clip; `video` is the confirmed field
     name — there is no documented plain-image entry type). Writes
     preprocessed tensors to `.precomputed/` under the working directory.
  2. `python scripts/train.py <config.yaml>` — config-file-driven, not
     flag-driven. Needs (at minimum) `model.model_path`,
     `model.text_encoder_path` (a DIRECTORY, not a single file — LTX-2's
     training path needs the full-precision Gemma checkpoint, not the fp4
     single-file variant this codebase downloads for *inference*, see
     app/media/workflows/README.md), `data.preprocessed_data_root`
     (the `.precomputed/` dir from step 1), `output_dir`, and `lora.rank`/
     `optimization.steps`/`learning_rate`. Trained weights land under
     `<output_dir>/checkpoints/lora_weights_step_NNNNN.safetensors`.

**Two real open questions this module can't resolve from docs alone —
recommend a manual first training run (same posture as the manual Serverless
inference validation) before trusting the automated /train-lora endpoint
against a real character:**

  1. Whether a still image is an acceptable `video` entry, or must be a
     real (even trivially short) video file. This module's pragmatic
     choice below — ffmpeg-loop each uploaded still into a short static
     clip on the training pod — is a common workaround for identity-style
     LoRA training in other video-model trainers, not a confirmed-correct
     answer for ltx-trainer specifically.
  2. The exact checkpoint/text-encoder sources ltx-trainer's `model_path`/
     `text_encoder_path` expect for *training* (as opposed to the
     confirmed fp8 inference checkpoint) — configurable below via
     LTX_TRAINING_CHECKPOINT_REPO/FILE and LTX_TRAINING_TEXT_ENCODER_REPO
     rather than hardcoded, since neither has been live-validated yet.

The training pod does NOT mount the Network Volume (see module docstring
above), so it downloads its own copy of these on every run — real disk/
time cost, on top of GPU-hours, worth watching once real numbers exist."""
import ipaddress
import json
import logging
import os
import shlex
import socket
import time
from urllib.parse import urlparse

logger = logging.getLogger("culturix.services.culturetoon_lora")

MIN_LORA_TRAINING_IMAGES = 10
# Confirmed live 2026-08-23: a real, previously fully-successful training
# run's own train.py process alone (from "Starting training..." to the
# final checkpoint) took ~70+ minutes — already close to the old 3600s
# (1hr) ceiling with zero margin. A later retry (1001 steps, one more than
# before) then genuinely exceeded 3600s, and the poll loop's own timeout
# path terminated the pod via the normal cleanup flow while training was
# still legitimately running — an entire near-complete run lost to an
# overly tight ceiling, not a real failure. There's no cost to a generous
# timeout here (the poll loop returns as soon as the process actually
# finishes, whatever that takes), only cost to cutting a real job short,
# so this errs well past the largest duration observed so far.
_TRAINING_TIMEOUT_SECONDS = 7200  # ~2hr ceiling for one character's LoRA run
# Confirmed live 2026-08-26: wait_for_ssh_ready's own 180s default was too
# tight for this training image specifically — a freshly-allocated COMMUNITY
# pod pulling ghcr.io/.../culturix-ltx-training:latest (a large custom torch/
# cu126 + ltx-trainer image) cold, with no layer cache on that host, can
# still be mid-pull when the default deadline hits, surfacing as "no SSH
# port exposed yet" even though the pod was never actually broken — just
# still booting. Same reasoning as _TRAINING_TIMEOUT_SECONDS above: no cost
# to a generous timeout here since the poll loop returns the moment SSH is
# actually reachable.
_SSH_READY_TIMEOUT_SECONDS = 900
_DOWNLOAD_TIMEOUT_SECONDS = 1800  # training pod fetches its own models fresh every run
# Where the LoRA lands on the Network Volume, relative to the volume root —
# same directory ComfyUI's LoraLoaderModelOnly node reads from
# (app/media/ltx_workflow.py).
_VOLUME_LORA_KEY_PREFIX = "ComfyUI/models/loras"
# Confirmed live 2026-08-21: the previous 768x1360 value was wrong on two
# counts — ltx-trainer's process_dataset.py rejected it outright
# ("Width and height must be multiples of 32x32"; 1360 isn't), and even if
# it had passed, it didn't actually match the real inference canvas — the
# self-hosted video workflow (app/media/workflows/ltx_text_to_video.json)
# renders 720x1280, not 768x1360, so the old comment's "matches the
# inference canvas" claim was itself stale. 720 also isn't a multiple of
# 32; 704 is the nearest one (16px under, vs. 736's 16px over — picked the
# smaller/cheaper option since the deviation from a true 9:16 canvas is
# identical either way).
_RESOLUTION_BUCKET = "704x1280x49"  # vertical ~9:16, ~2s at 24fps — nearest 32-multiple to the real 720x1280 inference canvas
# UNVERIFIED (see module docstring's open question #2) — override via env
# vars once confirmed against a real training run rather than editing code.
_CHECKPOINT_REPO = os.getenv("LTX_TRAINING_CHECKPOINT_REPO", "Lightricks/LTX-2.3")
_CHECKPOINT_FILE = os.getenv("LTX_TRAINING_CHECKPOINT_FILE", "ltx-2.3-22b-dev.safetensors")
_TEXT_ENCODER_REPO = os.getenv("LTX_TRAINING_TEXT_ENCODER_REPO", "google/gemma-3-12b-it")
# Network Volume cache keys for the above — see the caching logic in
# train_character_lora for why (repeat runs re-downloading the same
# ~30-40GB+ from HuggingFace on an expensive GPU-hour pod, for a phase
# that's purely network/disk-bound). Keyed by repo name so a changed
# LTX_TRAINING_*_REPO env var naturally misses the old cache instead of
# silently serving a stale/wrong model.
_CHECKPOINT_CACHE_KEY = f"training-cache/checkpoint/{_CHECKPOINT_REPO.replace('/', '_')}/{_CHECKPOINT_FILE}"
_TEXT_ENCODER_CACHE_KEY = f"training-cache/text_encoder/{_TEXT_ENCODER_REPO.replace('/', '_')}.tar"
# google/gemma-3-12b-it is a gated HuggingFace model — downloading it needs
# an authenticated token whose account has accepted Gemma's license, not
# just a repo name. Read here (not baked into the training image) so the
# same token works regardless of which pod/run uses it. Left unset by
# default rather than pre-validated — same lazy-fail posture as
# RUNPOD_SERVERLESS_ENDPOINT_ID elsewhere in this codebase; a missing/
# invalid token surfaces as an authenticated-download failure from `hf
# download` itself, caught by the existing _run() error handling below.
_HF_TOKEN = os.getenv("HF_TOKEN", "")


_CAPTION_PROMPT_TEMPLATE = (
    "This is a reference image of a cartoon character named {name}. Write ONE short "
    "caption (under 25 words) describing ONLY what's actually visible in THIS image: "
    "the character's pose, facial expression, camera framing, and background/setting. "
    "Start the caption with \"{name}\". Do not describe the character's appearance/"
    "design itself (that's constant across all their reference images) — only what "
    "varies in this specific shot. Return ONLY the caption text, nothing else."
)


class LoraTrainingError(Exception):
    pass


def _is_safe_external_url(url: str) -> bool:
    """SSRF guard for caption_training_image()'s Claude-vision fallback,
    which fetches `url` server-side via httpx.get() — every caller today
    only ever passes our own Supabase Storage URLs (see
    add_training_images()), but this function accepts an arbitrary string
    by signature, so it defends itself rather than relying on callers to
    stay that way forever. Resolves the hostname and rejects anything that
    lands on a private/loopback/link-local/reserved/multicast address —
    blocks the classic SSRF targets (localhost, RunPod/Docker-internal
    hosts, the 169.254.169.254 cloud-metadata endpoint) without needing an
    allowlist of specific external hosts."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        for family, _type, _proto, _canon, sockaddr in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def caption_training_image(image_url: str, character_name: str) -> str:
    """Vision-LLM caption for a single training image, describing what
    varies (pose, expression, framing, background) while keeping the
    character's name as a fixed leading token — the standard trigger-word
    + variable-description convention for identity LoRA training. Without
    this, every training clip would get the same caption (just the
    character's name), which teaches the LoRA that whatever's IDENTICAL
    across every image — a pose, a background, a camera angle — is part of
    the character's identity, not incidental; the model overfits to a
    single look instead of learning what's actually invariant (see
    CharacterVariant.lora_training_images's docstring). Same Qwen-max
    primary / Claude Haiku fallback pattern as culturetoon_relationship.py,
    using each provider's vision-capable variant. Fails open to a bare
    character-name caption on any error (network, rate limit, bad
    response) — a missing/weak caption shouldn't block an image upload."""
    prompt = _CAPTION_PROMPT_TEMPLATE.format(name=character_name)
    try:
        if os.getenv("QWEN_API_KEY"):
            from openai import OpenAI
            client = OpenAI(api_key=os.environ["QWEN_API_KEY"], base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
            response = client.chat.completions.create(
                model="qwen-vl-max",
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ]}],
            )
            caption = (response.choices[0].message.content or "").strip()
        else:
            import base64
            import httpx
            import anthropic
            resp = httpx.get(image_url, timeout=30)
            resp.raise_for_status()
            media_type = resp.headers.get("content-type", "image/png").split(";")[0]
            image_b64 = base64.b64encode(resp.content).decode("ascii")
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": prompt},
                ]}],
            )
            caption = (message.content[0].text or "").strip()
        return caption or character_name
    except Exception:
        logger.exception("Training-image captioning failed for %s — falling back to a bare name caption", image_url)
        return character_name


def add_training_images(variant, urls: list) -> None:
    """Appends manually-uploaded SUPPLEMENTAL images to the variant's
    training set, each captioned individually via caption_training_image()
    at upload time. Not the primary source of training data — see
    curate_training_images() below, which Culturix builds automatically
    from the character's own already-generated Expression images and
    rarely needs any manual upload at all. This exists for the cases that
    still benefit from it (e.g. a specific real reference photo the brand
    owner wants blended in), merged into curate_training_images()'s output
    rather than replacing it. Caller (the router) owns save_image()/
    storage.upload() for each file and the session commit — this does the
    captioning + list bookkeeping."""
    existing = variant.lora_training_images or []
    new_entries = [{"url": url, "caption": caption_training_image(url, variant.name)} for url in urls]
    variant.lora_training_images = existing + new_entries


def curate_training_images(session, variant) -> list:
    """Builds the LoRA training set Culturix decides on, not the user.
    Primary source: every one of this variant's already-generated
    Expression images (up to 10, one per EXPRESSION_NAMES entry — see
    app/models/expression.py — each a distinct AI-rendered pose already in
    the character's own illustrated art style) plus the variant's own
    canonical portrait. Captions are deterministic, not vision-LLM-guessed
    — we already know exactly what each Expression image depicts from its
    own `name` column, which is both free and more reliable than
    caption_training_image()'s best-effort guess.

    This beats asking a brand owner to source their own reference photos:
    real photos would be a different art style/medium than what the
    character actually needs reproduced, and generating a full Expression
    set is already something most variants go through as a normal part of
    character setup (see CharacterVariant's docstring on Expressions) — so
    for most variants, meaningful LoRA training data exists with zero
    separate curation step. Falls short of MIN_LORA_TRAINING_IMAGES only
    when a variant's own Expression set is still incomplete, which is a
    real and correct signal to surface (finish generating expressions
    first) rather than something to paper over.

    Deduplicated by URL and merged with any manually-uploaded supplemental
    images (add_training_images) — those keep their own vision-LLM
    captions rather than being recaptioned here. Read-only against the
    session (no writes) — safe to call from both the /train-lora
    pre-check and train_character_lora() itself."""
    from app.models.expression import Expression
    import uuid as _uuid

    entries = []
    seen_urls = set()

    if variant.image_url and variant.image_url not in seen_urls:
        entries.append({"url": variant.image_url, "caption": f"{variant.name}, neutral reference pose"})
        seen_urls.add(variant.image_url)

    expressions = (
        session.query(Expression)
        .filter_by(character_variant_id=_uuid.UUID(str(variant.id)))
        .order_by(Expression.name.asc())
        .all()
    )
    for expression in expressions:
        if expression.image_url and expression.image_url not in seen_urls:
            entries.append({
                "url": expression.image_url,
                "caption": f"{variant.name}, {expression.name.lower()} expression",
            })
            seen_urls.add(expression.image_url)

    for manual_entry in (variant.lora_training_images or []):
        url = manual_entry.get("url")
        if url and url not in seen_urls:
            entries.append(manual_entry)
            seen_urls.add(url)

    return entries


_FINALIZE_RETRY_ATTEMPTS = 6
_FINALIZE_RETRY_BACKOFF_SECONDS = 15


def _resilient(fn, *args, **kwargs):
    """Retries a network call a few times with a short backoff before
    giving up. Confirmed live 2026-08-23: a transient LOCAL connection
    blip during the SFTP checkpoint download (after training had already
    fully succeeded — 1001/1001 steps, real checkpoint on disk) crashed
    the whole finalize step, which then hit the unconditional `finally:
    terminate_pod()` in train_character_lora and threw the entire
    completed run away over what was a recoverable hiccup, not a real
    failure. The training step itself already tolerates this class of
    blip (backgrounded + polled with short-lived connections); the
    finalize steps (find checkpoint, SFTP download, S3 upload/verify)
    didn't, despite being just as exposed to the same local network
    instability. This wraps those calls the same way."""
    last_exc = None
    for attempt in range(_FINALIZE_RETRY_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Finalize step %s attempt %d/%d failed: %s",
                getattr(fn, "__name__", repr(fn)), attempt + 1, _FINALIZE_RETRY_ATTEMPTS, exc,
            )
            if attempt < _FINALIZE_RETRY_ATTEMPTS - 1:
                time.sleep(_FINALIZE_RETRY_BACKOFF_SECONDS)
    raise last_exc


def _run(runpod_ssh, host, port, command, timeout_seconds, error_prefix):
    exit_code, stdout, stderr = runpod_ssh.run_remote_command(host, port, command, timeout_seconds=timeout_seconds)
    if exit_code != 0:
        # Confirmed live 2026-08-20: stderr alone can be just boilerplate
        # hint/warning noise (e.g. hf CLI's Rich-formatted output goes to
        # stdout even on failure) — discarding stdout hid the actual error.
        combined = (stdout + "\n" + stderr) if stdout else stderr
        raise LoraTrainingError(f"{error_prefix}: {combined[-2000:]}")


_BACKGROUNDED_POLL_INTERVAL_SECONDS = 30


def _run_backgrounded(runpod_ssh, host, port, q, work_dir, command, timeout_seconds, label, error_prefix):
    """Launches `command` detached (nohup) and polls its liveness with
    short, separate SSH connections instead of blocking on one connection
    held open for the whole run. Confirmed live 2026-08-23/24, repeatedly,
    with no concurrent SSH activity: a single exec_command channel held
    open across a long-running, mostly-silent command (training, or a
    large curl/S3 transfer) got forcibly closed partway through — the
    remote process kept running and completed successfully moments later
    every time, but the result was lost anyway because reading it depended
    on that one connection surviving. Backgrounding the process and
    polling with fresh short-lived connections means no single connection
    needs to survive the full run — if one poll's connection has an
    issue, the remote process itself is entirely unaffected and the next
    poll just reconnects. `label` namespaces the log/status/script files
    so concurrent uses (e.g. checkpoint download vs. training) don't
    collide. Returns the log output on success (exit 0); raises
    LoraTrainingError otherwise."""
    log_path = f"{work_dir}/{label}.log"
    status_path = f"{work_dir}/{label}.status"
    script_path = f"{work_dir}/{label}.sh"
    script_content = f"{command}\necho EXIT:$? > {status_path}\n"
    _run(runpod_ssh, host, port,
         f"cat > {q(script_path)} << 'CULTURIX_EOF'\n{script_content}\nCULTURIX_EOF",
         30, f"Failed to write the {label} launch script on the training pod")

    launch_cmd = f"nohup bash {q(script_path)} > {q(log_path)} 2>&1 & echo $!"
    exit_code, stdout, stderr = runpod_ssh.run_remote_command(host, port, launch_cmd, timeout_seconds=30)
    pid = (stdout or "").strip()
    if exit_code != 0 or not pid.isdigit():
        raise LoraTrainingError(f"Failed to launch backgrounded {label}: {(stderr or stdout)[-1000:]}")
    logger.info("%s launched on pod as PID %s, polling every %ds", label, pid, _BACKGROUNDED_POLL_INTERVAL_SECONDS)

    # Check first, then sleep only if still alive — so a process that's
    # already finished by the time we get here (or a test double that
    # answers DEAD immediately) doesn't pay a full poll interval's wait
    # for nothing.
    deadline = time.time() + timeout_seconds
    while True:
        _, check_out, _ = runpod_ssh.run_remote_command(
            host, port, f"kill -0 {pid} 2>/dev/null && echo ALIVE || echo DEAD", timeout_seconds=20,
        )
        if (check_out or "").strip() == "DEAD":
            break
        if time.time() >= deadline:
            raise LoraTrainingError(
                f"{label} did not finish within {timeout_seconds}s (pid {pid} may still be running on the pod — "
                "check the RunPod console manually before assuming it's stuck)"
            )
        time.sleep(_BACKGROUNDED_POLL_INTERVAL_SECONDS)

    _, status_out, _ = runpod_ssh.run_remote_command(host, port, f"cat {q(status_path)} 2>/dev/null", timeout_seconds=20)
    _, log_out, _ = runpod_ssh.run_remote_command(host, port, f"tail -c 4000 {q(log_path)} 2>/dev/null", timeout_seconds=20)
    status_out = (status_out or "").strip()
    if not status_out.startswith("EXIT:"):
        raise LoraTrainingError(f"{label} exited but no status file was found — log tail: {(log_out or '')[-2000:]}")
    remote_exit_code = int(status_out.split(":", 1)[1].strip() or "1")
    if remote_exit_code != 0:
        raise LoraTrainingError(f"{error_prefix} (exit {remote_exit_code}): {(log_out or '')[-2000:]}")
    return log_out


_S3_ENV_VARS = (
    "RUNPOD_S3_ACCESS_KEY_ID", "RUNPOD_S3_SECRET_ACCESS_KEY",
    "RUNPOD_S3_ENDPOINT_URL", "RUNPOD_S3_REGION", "RUNPOD_S3_BUCKET",
)


def _download_from_cache(runpod_ssh, host, port, q, work_dir, key, local_path, label):
    """Downloads `key` from the Network Volume straight to `local_path` on
    the pod, via credential-injected boto3 running ON the pod — NOT a
    presigned URL. Confirmed live 2026-08-24: RunPod's S3-compatible API
    rejects every presigned GET URL boto3 can generate with `401
    AccessDenied: missing Authorization header`, even with a correctly
    SigV4-signed query string — it only accepts header-based auth, not
    real S3's query-string presigned-URL scheme (see
    runpod_s3.presigned_get_url's docstring). This does put real,
    read-only S3 credentials on the ephemeral training pod, which the
    original presigned-URL design deliberately avoided — an acceptable
    relaxation here since (a) it's the only way this actually works
    against RunPod's backend, (b) these credentials only grant read
    access to a shared, non-sensitive model checkpoint, not any user
    data, and (c) the pod is terminated right after this function
    returns either way. Downloads (unlike RunPod's own broken multipart
    uploads) use plain ranged GET requests under the hood, a much
    simpler and more universally-supported mechanism, via boto3's own
    managed transfer (multi-threaded, resumable per-chunk internally)."""
    missing = [var for var in _S3_ENV_VARS if not os.environ.get(var)]
    if missing:
        raise LoraTrainingError(f"Cannot download cached {label}: missing env var(s) {', '.join(missing)}")

    download_script = f"""
import boto3
s3 = boto3.client(
    "s3",
    aws_access_key_id={os.environ['RUNPOD_S3_ACCESS_KEY_ID']!r},
    aws_secret_access_key={os.environ['RUNPOD_S3_SECRET_ACCESS_KEY']!r},
    endpoint_url={os.environ['RUNPOD_S3_ENDPOINT_URL']!r},
    region_name={os.environ['RUNPOD_S3_REGION']!r},
)
s3.download_file({os.environ['RUNPOD_S3_BUCKET']!r}, {key!r}, {local_path!r})
"""
    script_path = f"{work_dir}/{label}_download.py"
    _run(runpod_ssh, host, port,
         f"cat > {q(script_path)} << 'CULTURIX_EOF'\n{download_script}\nCULTURIX_EOF",
         30, f"Failed to write the {label} download script on the training pod")
    _run(runpod_ssh, host, port, "pip install -q boto3", 300, "Failed to install boto3 on the training pod")
    _run_backgrounded(
        runpod_ssh, host, port, q, work_dir,
        f"python3 -u {q(script_path)}",
        _DOWNLOAD_TIMEOUT_SECONDS, label,
        f"Failed to download the cached {label} from the Network Volume",
    )


def _upload_to_volume_from_pod(runpod_ssh, host, port, q, work_dir, local_path, key, label="lora_upload"):
    """Uploads `local_path` (on the pod) straight to the Network Volume at
    `key`, via credential-injected boto3 running ON the pod — instead of
    SFTPing the file back to our own orchestrator first and pushing it to
    S3 from there in a second hop. Confirmed live 2026-08-25: the SFTP-
    then-S3-push design left a FULLY successful training run stuck —
    paramiko's SFTP read hung/dropped repeatedly on the same proxy-layer
    connection instability documented elsewhere in this file, and even
    with a socket timeout and retries in place, the user ended up having
    to manually log into the pod's web terminal and push the file to S3
    themselves to unblock it. Cutting the SFTP hop entirely removes that
    whole failure class rather than adding more retries around it — the
    LoRA file is small (rank-32 adapter weights, well under RunPod's
    500MB single-PutObject cap), so this is a plain, non-multipart
    upload, the same operation that worked cleanly by hand. Same
    accepted trust relaxation as _download_from_cache: real (this time
    write-capable) S3 credentials briefly touch the ephemeral,
    terminated-right-after training pod."""
    missing = [var for var in _S3_ENV_VARS if not os.environ.get(var)]
    if missing:
        raise LoraTrainingError(f"Cannot upload trained LoRA: missing env var(s) {', '.join(missing)}")

    upload_script = f"""
import boto3
s3 = boto3.client(
    "s3",
    aws_access_key_id={os.environ['RUNPOD_S3_ACCESS_KEY_ID']!r},
    aws_secret_access_key={os.environ['RUNPOD_S3_SECRET_ACCESS_KEY']!r},
    endpoint_url={os.environ['RUNPOD_S3_ENDPOINT_URL']!r},
    region_name={os.environ['RUNPOD_S3_REGION']!r},
)
s3.upload_file({local_path!r}, {os.environ['RUNPOD_S3_BUCKET']!r}, {key!r})
"""
    script_path = f"{work_dir}/{label}.py"
    _run(runpod_ssh, host, port,
         f"cat > {q(script_path)} << 'CULTURIX_EOF'\n{upload_script}\nCULTURIX_EOF",
         30, f"Failed to write the {label} script on the training pod")
    _run(runpod_ssh, host, port, "pip install -q boto3", 300, "Failed to install boto3 on the training pod")
    _run_backgrounded(
        runpod_ssh, host, port, q, work_dir,
        f"python3 -u {q(script_path)}",
        _DOWNLOAD_TIMEOUT_SECONDS, label,
        f"Failed to upload {key} to the Network Volume",
    )


def train_character_lora(variant, session) -> None:
    """Synchronous end-to-end training run: curates the training set
    (curate_training_images() — Culturix's own already-generated Expression
    images by default, not a manually-uploaded set), creates a fresh
    ephemeral training pod, downloads that pod's own copy of the
    training-variant checkpoint/text-encoder (it doesn't mount the Network
    Volume, see module docstring), stages the curated images and converts
    each into a short static clip (ltx-trainer's dataset format is
    video+caption pairs, not bare stills — see module docstring's open
    question #1), preprocesses + runs ltx-trainer's real two-stage CLI over
    SSH, SFTP-downloads the resulting LoRA back to this process, pushes it
    to the Network Volume via its S3-compatible API, and verifies the
    upload landed before setting lora_path (a bare filename, not a URL)/
    lora_status. Mutates `variant` in place — caller owns the session
    commit, same convention as every other CultureToons service function.
    `session` is needed to query this variant's Expression rows
    (curate_training_images() reads them) — not otherwise written to here.
    Raises LoraTrainingError on any failure (also setting
    lora_status="failed" first, so a failed attempt is visible even if the
    caller doesn't handle the exception specially). The training pod is
    always terminated, success or failure — it's ephemeral by design,
    never worth keeping around."""
    from app.media import runpod_client, runpod_ssh, runpod_s3

    training_images = curate_training_images(session, variant)
    if len(training_images) < MIN_LORA_TRAINING_IMAGES:
        raise LoraTrainingError(
            f"Need at least {MIN_LORA_TRAINING_IMAGES} training images, have {len(training_images)}"
        )

    variant.lora_status = "training"
    variant.lora_error = None
    pod_id = None

    try:
        pod_id = runpod_client.create_training_pod_with_retry()
        host, port = runpod_client.wait_for_ssh_ready(pod_id, timeout_seconds=_SSH_READY_TIMEOUT_SECONDS)

        # Every value interpolated into a shell command below is passed
        # through shlex.quote(), including ones built purely from a UUID/
        # loop index that are safe under every caller reachable today
        # (curate_training_images() only ever surfaces our own storage
        # URLs — see that function's docstring) — this is defense in
        # depth, not a response to a currently-exploitable path, since a
        # future caller or storage-layer bug could otherwise turn an
        # unescaped `curl '{url}'` into command injection on a pod holding
        # live SSH/S3 credentials.
        q = shlex.quote

        work_dir = f"/workspace/lora_training/{variant.id}"
        models_dir = f"{work_dir}/models"
        output_dir = f"{work_dir}/output"
        _run(runpod_ssh, host, port,
             f"mkdir -p {q(work_dir)} {q(models_dir + '/checkpoint')} {q(models_dir + '/text_encoder')} {q(output_dir)}",
             120, "Failed to set up the training pod's working directory")

        # HF_HUB_DISABLE_XET=1 on every hf download here — confirmed live
        # 2026-08-20, twice: hf_xet's accelerated transfer path stalled
        # indefinitely (manual Gemma-repo download on a Pod) and separately
        # raised "File reconstruction error: Internal Wr..." (this training
        # pod's checkpoint download) on the exact same class of large/gated
        # repo fetch. Plain HTTP download (what disabling xet falls back
        # to) is slower but has been reliable both times it was tried.
        # HF_HUB_DISABLE_PROGRESS_BARS=1 alongside it — confirmed live: a
        # failed download's captured stderr was missing the actual
        # exception message entirely, cut off right at the last traceback
        # frame. hf's progress bar repaints its line via carriage returns,
        # not real terminal control, over a non-interactive SSH
        # exec_command channel (no real TTY) — raw \r-separated output
        # captured as a plain string is a likely source of that lost tail.
        # Disabling the progress bar removes that whole class of
        # non-interactive-terminal corruption, not just this one guess.
        xet_env = "HF_HUB_DISABLE_XET=1 HF_HUB_DISABLE_PROGRESS_BARS=1 "

        # This pod's own model copy — the Network Volume isn't mounted here.
        # Confirmed live 2026-08-23: this ~30-40GB+ checkpoint (and the text
        # encoder below) was getting re-downloaded from HuggingFace from
        # scratch on EVERY run, on an expensive GPU-hour pod, for a phase
        # that's purely network/disk-bound and doesn't need the GPU at all
        # — real, compounding cost across every run and every retry.
        # Caching a copy on the Network Volume (checked via a cheap HEAD
        # request) lets every run AFTER the first skip HuggingFace entirely.
        # Falls back to today's unmodified hf download if the cache doesn't
        # exist yet (the very first run, or a different checkpoint/text-
        # encoder configured via the LTX_TRAINING_* env vars). Cache
        # population itself isn't done here — a one-time backfill, not a
        # per-run concern.
        checkpoint_path = f"{models_dir}/checkpoint/{_CHECKPOINT_FILE}"
        if runpod_s3.verify_exists(_CHECKPOINT_CACHE_KEY):
            _download_from_cache(runpod_ssh, host, port, q, work_dir, _CHECKPOINT_CACHE_KEY, checkpoint_path, "checkpoint_cache_dl")
        else:
            _run(runpod_ssh, host, port,
                 f"{xet_env}hf download {q(_CHECKPOINT_REPO)} {q(_CHECKPOINT_FILE)} --local-dir {q(models_dir + '/checkpoint')}",
                 _DOWNLOAD_TIMEOUT_SECONDS, "Failed to download the training checkpoint")

        text_encoder_dir = f"{models_dir}/text_encoder"
        if runpod_s3.verify_exists(_TEXT_ENCODER_CACHE_KEY):
            text_encoder_tar = f"{models_dir}/text_encoder.tar"
            _download_from_cache(runpod_ssh, host, port, q, work_dir, _TEXT_ENCODER_CACHE_KEY, text_encoder_tar, "text_encoder_cache_dl")
            _run(runpod_ssh, host, port,
                 f"mkdir -p {q(text_encoder_dir)} && tar -xf {q(text_encoder_tar)} -C {q(text_encoder_dir)}",
                 300, "Failed to extract the cached text encoder tar")
        else:
            # google/gemma-3-12b-it is gated — this download will fail with an
            # authentication error if HF_TOKEN isn't set to a token whose
            # account has accepted Gemma's license on huggingface.co.
            #
            # Goes through huggingface_hub's Python API (snapshot_download),
            # not the `hf` CLI, specifically for the token to actually reach
            # it — confirmed live 2026-08-26, twice: neither an `HF_TOKEN=`
            # env-var prefix nor an explicit `--token` flag on `hf download`
            # stopped this exact call from hitting "Access denied. This
            # repository requires approval." / "sending unauthenticated
            # requests", even with a token independently verified (direct
            # HTTPS GET against a real gated file in this repo, from this
            # process, using this exact token) to have real access. Whatever
            # the training image's installed `hf` CLI is doing with a token
            # handed to it, it isn't using it — calling snapshot_download()
            # directly with token= as an explicit function argument removes
            # the CLI's own token-resolution logic from the picture entirely
            # instead of guessing at another flag/env spelling for it.
            hf_download_script = f"""
from huggingface_hub import snapshot_download
snapshot_download(repo_id={_TEXT_ENCODER_REPO!r}, local_dir={text_encoder_dir!r}, token={_HF_TOKEN!r})
"""
            hf_script_path = f"{work_dir}/hf_text_encoder_download.py"
            _run(runpod_ssh, host, port,
                 f"cat > {q(hf_script_path)} << 'CULTURIX_EOF'\n{hf_download_script}\nCULTURIX_EOF",
                 30, "Failed to write the text encoder download script on the training pod")
            _run(runpod_ssh, host, port,
                 f"{xet_env}python3 -u {q(hf_script_path)}",
                 _DOWNLOAD_TIMEOUT_SECONDS, "Failed to download the training text encoder (is HF_TOKEN set and Gemma's license accepted on huggingface.co for that account?)")
            # Self-healing cache population: the standalone one-time backfill
            # script for this exact tar kept failing on its own upload step
            # (never confirmed to complete), leaving every run since paying
            # this same slow gated HF download. Populating it here instead —
            # right after we already have a fresh, known-good copy on disk —
            # means the run that hits the cache miss is also the run that
            # fixes it for everyone after it. Best-effort: a cache-population
            # failure shouldn't fail a training run that otherwise has
            # everything it needs to proceed.
            try:
                text_encoder_tar = f"{models_dir}/text_encoder.tar"
                _run(runpod_ssh, host, port,
                     f"tar -cf {q(text_encoder_tar)} -C {q(text_encoder_dir)} .",
                     300, "Failed to tar the downloaded text encoder for caching")
                _upload_to_volume_from_pod(
                    runpod_ssh, host, port, q, work_dir, text_encoder_tar, _TEXT_ENCODER_CACHE_KEY,
                    label="text_encoder_cache_ul",
                )
            except Exception:
                logger.warning("Failed to populate the text-encoder Network Volume cache — will retry on a future run", exc_info=True)

        # Stage each reference image, then loop it into a short static clip
        # — see module docstring's open question #1 on why. Each clip keeps
        # its own real caption (from add_training_images/
        # caption_training_image) rather than a repeated character name —
        # see CharacterVariant.lora_training_images's docstring for why a
        # flat repeated caption would actively hurt training quality.
        clip_entries = []
        for i, entry in enumerate(training_images):
            url = entry["url"]
            caption = (entry.get("caption") or "").strip() or variant.name
            img_path = f"{work_dir}/img_{i:03d}.png"
            clip_path = f"{work_dir}/clip_{i:03d}.mp4"
            width, height, frames = _RESOLUTION_BUCKET.split("x")
            # Confirmed live 2026-08-21: `frames` was parsed but never
            # actually applied — the old `-t 2 -r 24` targets ~48 frames,
            # not exactly the bucket's declared 49, and process_dataset.py's
            # resolution-bucket matching requires an EXACT frame-count
            # match. Every clip silently failed to match any bucket during
            # Phase 2 (video latents) while Phase 1 (captions, which don't
            # need exact frame counts) succeeded fine — exit code 0, no
            # error, just an empty latents/ directory. -frames:v guarantees
            # the exact count regardless of ffmpeg's -t/-r rounding.
            stage_cmd = (
                f"curl -sL --fail {q(url)} -o {q(img_path)} && "
                f"ffmpeg -y -loop 1 -i {q(img_path)} -frames:v {frames} -r 24 -pix_fmt yuv420p "
                f"-vf scale={width}:{height} {q(clip_path)}"
            )
            _run(runpod_ssh, host, port, stage_cmd, 120, f"Failed to stage/convert training image {i}")
            clip_entries.append({"caption": caption, "video": clip_path})

        dataset_json = json.dumps(clip_entries)
        dataset_path = f"{work_dir}/dataset.json"
        # Heredoc body content isn't a command argument, so shlex.quote()
        # doesn't apply here — the relevant protection is the QUOTED
        # delimiter ('CULTURIX_EOF', not CULTURIX_EOF), which disables
        # variable/command substitution inside the body entirely. The one
        # remaining risk (body content containing a bare line that exactly
        # matches the delimiter, prematurely closing it) can't happen here
        # since json.dumps() with no `indent` never emits a literal
        # newline byte — the whole payload is always a single line.
        _run(runpod_ssh, host, port,
             f"cat > {q(dataset_path)} << 'CULTURIX_EOF'\n{dataset_json}\nCULTURIX_EOF",
             30, "Failed to write dataset.json on the training pod")

        precomputed_dir = f"{work_dir}/.precomputed"
        preprocess_cmd = (
            f"cd /workspace/LTX-2/packages/ltx-trainer && "
            f"python scripts/process_dataset.py {q(dataset_path)} "
            f"--resolution-buckets {q(_RESOLUTION_BUCKET)} "
            f"--model-path {q(checkpoint_path)} --text-encoder-path {q(text_encoder_dir)} "
            f"--output-dir {q(precomputed_dir)}"
        )
        _run(runpod_ssh, host, port, preprocess_cmd, _TRAINING_TIMEOUT_SECONDS, "ltx-trainer dataset preprocessing failed")
        config_yaml = (
            f"seed: 42\n"
            f"output_dir: \"{output_dir}\"\n"
            f"model:\n"
            f"  model_path: \"{checkpoint_path}\"\n"
            f"  text_encoder_path: \"{text_encoder_dir}\"\n"
            f"  training_mode: \"lora\"\n"
            f"lora:\n"
            f"  rank: 32\n"
            f"  alpha: 32\n"
            f"optimization:\n"
            f"  learning_rate: 1e-4\n"
            # Confirmed live 2026-08-23: 1000 (an exact multiple of
            # checkpoints.interval below) is a real, upstream ltx-trainer
            # bug trigger — training's very last step is BOTH a periodic
            # checkpoint-interval boundary AND the unconditional
            # end-of-training save, so it saves the same
            # lora_weights_step_01000.safetensors twice under the same
            # filename, and the second save's keep_last_n=1 cleanup deletes
            # the file it just re-wrote (confirmed via the real training
            # log: "Lora weights for step 1000 saved" followed immediately
            # by "Removed old checkpoint: ...lora_weights_step_01000...").
            # This is how a fully successful training run still ended with
            # zero recoverable output. 1001 is not a multiple of 250, so
            # the periodic save (step 1000) and the final save (step 1001)
            # land on genuinely different filenames and never collide.
            f"  steps: 1001\n"
            f"  batch_size: 1\n"
            # Confirmed live 2026-08-21: the base checkpoint is a 22B-param
            # transformer — even training LoRA-only (base weights frozen),
            # activation memory during the forward/backward pass exhausted
            # an 80GB GPU by just 98MiB (torch.OutOfMemoryError deep inside
            # a peft LoRA layer's forward). enable_gradient_checkpointing
            # trades recompute for a large activation-memory cut, the
            # standard fix for exactly this shape of near-miss OOM —
            # confirmed available in ltx_trainer.config.OptimizationConfig
            # by reading it directly, not assumed.
            f"  enable_gradient_checkpointing: true\n"
            # Confirmed live 2026-08-23 by reading Lightricks' own example
            # config (configs/t2v_lora.yaml): their own default demo sets
            # checkpoints.interval: 250 — our config never set this,
            # silently taking CheckpointsConfig's own most fragile default
            # (None = intermediate checkpoints disabled entirely), which is
            # exactly why every connection interruption this session lost
            # the ENTIRE run instead of a partial one. keep_last_n: 1 (the
            # library default) is fine — this is a safety net against
            # losing all progress, not a full resume feature (each retry
            # still starts a fresh pod/directory), but it costs nothing and
            # matches the officially documented default.
            f"checkpoints:\n"
            f"  interval: 250\n"
            f"data:\n"
            f"  preprocessed_data_root: \"{precomputed_dir}\"\n"
        )
        config_path = f"{work_dir}/config.yaml"
        # Same heredoc reasoning as dataset.json above — every interpolated
        # value here is a path built purely from variant.id (a UUID), never
        # user text, so there's no bare-delimiter-line risk either.
        _run(runpod_ssh, host, port,
             f"cat > {q(config_path)} << 'CULTURIX_EOF'\n{config_yaml}\nCULTURIX_EOF",
             30, "Failed to write training config on the training pod")

        train_cmd = f"cd /workspace/LTX-2/packages/ltx-trainer && python scripts/train.py {q(config_path)}"
        _run_backgrounded(runpod_ssh, host, port, q, work_dir, train_cmd, _TRAINING_TIMEOUT_SECONDS, "train", "ltx-trainer training run failed")

        # The final checkpoint's exact step-count suffix isn't known ahead
        # of time — find the highest-numbered one ltx-trainer wrote. The
        # glob suffix is deliberately left outside shlex.quote() (quoting
        # it would defeat shell glob expansion); only the safe, UUID-built
        # output_dir prefix is quoted.
        exit_code, stdout, stderr = _resilient(
            runpod_ssh.run_remote_command,
            host, port,
            f"ls -1 {q(output_dir)}/checkpoints/lora_weights_step_*.safetensors 2>/dev/null | sort | tail -n 1",
            timeout_seconds=30,
        )
        local_output_path = (stdout or "").strip()
        if exit_code != 0 or not local_output_path:
            raise LoraTrainingError(f"Could not find a trained LoRA checkpoint under {output_dir}/checkpoints: {stderr[-1000:]}")

        lora_filename = f"{variant.id}.safetensors"
        volume_key = f"{_VOLUME_LORA_KEY_PREFIX}/{lora_filename}"
        _upload_to_volume_from_pod(runpod_ssh, host, port, q, work_dir, local_output_path, volume_key)
        if not _resilient(runpod_s3.verify_exists, volume_key):
            raise LoraTrainingError(
                f"Uploaded {volume_key} to the Network Volume but a HEAD check couldn't confirm it landed"
            )

        variant.lora_path = lora_filename
        variant.lora_status = "ready"
        logger.info("LoRA training complete for variant %s", variant.id)
    except LoraTrainingError as exc:
        variant.lora_status = "failed"
        # Tail, not head — confirmed live: a head slice here was cutting
        # off the actual exception message (the useful, specific part) at
        # the very end of a long remote traceback, leaving only generic
        # framework frames stored. See _run()'s own stderr[-N:] for the
        # same reasoning, one layer down.
        variant.lora_error = str(exc)[-2000:]
        logger.error("LoRA training failed for variant %s: %s", variant.id, exc)
        raise
    except Exception as exc:
        variant.lora_status = "failed"
        variant.lora_error = str(exc)[-2000:]
        logger.exception("LoRA training failed unexpectedly for variant %s", variant.id)
        raise LoraTrainingError(str(exc)) from exc
    finally:
        # Confirmed live 2026-08-21: a single terminate_pod() call left a
        # training pod running (and billing) for over an hour after a
        # transient local network blip made this one attempt fail (DNS
        # resolution error) — the exact class of failure most likely to
        # transiently break a single call, right when correctness matters
        # most. Retry a few times before giving up and logging loudly.
        if pod_id:
            for attempt in range(3):
                try:
                    runpod_client.terminate_pod(pod_id)
                    break
                except Exception:
                    if attempt == 2:
                        logger.exception(
                            "Failed to terminate RunPod training pod %s after 3 attempts — "
                            "check the RunPod console manually, it may still be billing", pod_id,
                        )
                    else:
                        time.sleep(5)


def run_lora_training(variant_id) -> None:
    """Background-task entry point (POST /variants/{id}/train-lora) — owns
    its own session lifecycle since it runs after the request's own session
    has already closed, same shape as generate_video_for_toon(user_id,
    toon_id) in app/services/culturetoon_video.py."""
    import uuid as _uuid
    from app.db import SessionLocal
    from app.models.character_variant import CharacterVariant

    session = SessionLocal()
    try:
        variant = session.query(CharacterVariant).filter_by(id=_uuid.UUID(str(variant_id))).first()
        if not variant:
            return
        try:
            train_character_lora(variant, session)
        except LoraTrainingError:
            pass  # already logged + lora_status="failed" set by train_character_lora
        # Confirmed live 2026-08-23: this exact commit died mid-flight to a
        # transient local network blip (psycopg2.OperationalError, server
        # closed the connection unexpectedly) immediately after a fully
        # successful training run — pool_pre_ping only detects a STALE
        # connection at checkout, it can't help a connection that dies
        # mid-request. A bare commit retry isn't enough here: SQLAlchemy
        # marks the session's transaction as needing rollback after a
        # failed flush, so a second commit() without rolling back first
        # would just raise PendingRollbackError instead of actually
        # retrying — roll back before each retry attempt.
        last_exc = None
        for attempt in range(_FINALIZE_RETRY_ATTEMPTS):
            try:
                session.commit()
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                session.rollback()
                logger.warning("session.commit() attempt %d/%d failed: %s", attempt + 1, _FINALIZE_RETRY_ATTEMPTS, exc)
                if attempt < _FINALIZE_RETRY_ATTEMPTS - 1:
                    time.sleep(_FINALIZE_RETRY_BACKOFF_SECONDS)
        if last_exc is not None:
            raise last_exc
    finally:
        session.close()


_PREVIEW_DURATION_SECONDS = 3
_PREVIEW_PROMPT = (
    "The character waves hello at the camera with a warm, friendly smile, "
    "standing in soft natural lighting."
)


class LoraPreviewError(Exception):
    pass


def run_lora_preview(variant_id, user_id) -> None:
    """Background-task entry point (POST /variants/{id}/lora-preview) —
    owns its own session lifecycle, same shape as run_lora_training.
    Generates one cheap, short self-hosted clip grounded in the variant's
    trained LoRA and nothing else (a fixed generic prompt, not a real
    script) — this is a sanity check on the LoRA itself, not a production
    generation. There's no automated quality signal for a trained LoRA
    otherwise: lora_status="ready" only means training completed and the
    file uploaded, not that it looks good — see this field's docstring on
    CharacterVariant. Always uses the allocation-retry client, same
    reasoning as generate_video_for_toon_selfhosted's interactive-button
    path: a single ad-hoc call can't assume a warm Serverless worker the
    way a batch runner's later jobs can. user_id is only needed for the
    GenerationUsage row (a NOT NULL column) — the request already
    authorized against it before backgrounding this."""
    import os
    import uuid as _uuid
    from app.db import SessionLocal
    from app.models.character import Character
    from app.models.character_variant import CharacterVariant
    from app.media import ltx_workflow, runpod_serverless_client, storage
    from app.services.culturetoon_usage import record_usage, estimate_selfhosted_video_cost

    session = SessionLocal()
    variant = None
    try:
        variant = session.query(CharacterVariant).filter_by(id=_uuid.UUID(str(variant_id))).first()
        if not variant:
            return
        try:
            if variant.lora_status != "ready" or not variant.lora_path:
                raise LoraPreviewError("This variant has no ready trained LoRA to preview")
            endpoint_id = os.getenv("RUNPOD_SERVERLESS_ENDPOINT_ID", "")
            if not endpoint_id:
                raise LoraPreviewError("RUNPOD_SERVERLESS_ENDPOINT_ID is not configured")

            workflow = ltx_workflow.build_workflow(
                _PREVIEW_PROMPT, _PREVIEW_DURATION_SECONDS, lora_path=variant.lora_path,
            )
            video_bytes = runpod_serverless_client.run_inference_job_with_allocation_retry(endpoint_id, workflow)

            video_url = storage.upload(
                video_bytes,
                f"culturetoons/{variant.character_id}/variants/{variant.id}/lora-preview-{_uuid.uuid4().hex[:8]}.mp4",
                "video/mp4",
            )
            variant.lora_preview_url = video_url
            variant.lora_preview_status = "ready"
            variant.lora_preview_error = None
        except Exception as exc:
            session.rollback()
            variant.lora_preview_status = "failed"
            variant.lora_preview_error = str(exc)[:2000]
            logger.warning("LoRA preview failed for variant %s: %s", variant_id, exc)
        session.commit()
    finally:
        if variant:
            # Recorded regardless of outcome, same reasoning as the
            # self-hosted toon-generation path — a failed generation
            # still burns real GPU time.
            character = session.query(Character).filter_by(id=variant.character_id).first()
            if character:
                record_usage(
                    session, user_id=user_id, brand_id=character.brand_id,
                    provider="runpod_ltx", generation_type="lora_preview",
                    output_units=_PREVIEW_DURATION_SECONDS,
                    cost_usd=estimate_selfhosted_video_cost(_PREVIEW_DURATION_SECONDS),
                )
                session.commit()
        session.close()

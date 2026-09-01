#!/usr/bin/env bash
# Downloads the LTX-2.5 model set onto a RunPod Network Volume, into the
# exact folders the official ComfyUI template's loader nodes ask for.
#
# Run this ON a pod that has the target Network Volume mounted (the
# carrier-pod relay in app/media/runpod_volume_relay.py rents one, or
# attach the volume to any pod and run this over SSH). Downloading via the
# pod keeps the transfer inside RunPod's network -- pulling ~40GB down to a
# laptop and back up again is the slow path that made the LoRA migration
# take ~30 min per file.
#
# Filenames below are read from the official template's own loader widgets
# (app/media/workflows/ltx25_official/video_ltx2_5_i2v.json), so they match
# what the graph will actually request from ComfyUI. Verified present in
# Lightricks/LTX-2.5 on 2026-09-01.
#
# Requires HF_TOKEN with LTX-2.5 terms accepted (gated=auto on that repo).
set -euo pipefail

VOLUME_ROOT="${VOLUME_ROOT:-/runpod-volume/ComfyUI}"
REPO="Lightricks/LTX-2.5"

if [ -z "${HF_TOKEN:-}" ]; then
  echo "HF_TOKEN must be set (the repo is gated -- accept terms at https://huggingface.co/$REPO)" >&2
  exit 1
fi

python3 -m pip install -q --upgrade "huggingface_hub[cli]>=0.24"

# repo_path:target_subdir
#
# The DISTILLED int8 transformer is what the official i2v/t2v templates
# pin: fast, and the variant those graphs were authored against. The BF16
# base (ltx-2.5-22b-dev-transformer-bf16.safetensors) is higher quality and
# slower -- swap the UNETLoader widget and re-check VRAM before using it.
FILES=(
  "diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors:models/diffusion_models"
  "text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors:models/text_encoders"
  "vae/ltx-2.5-video-vae-bf16.safetensors:models/vae"
  "vae/ltx-2.5-audio-vae-bf16.safetensors:models/vae"
  "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors:models/latent_upscale_models"
)

echo "Target volume root: $VOLUME_ROOT"
for entry in "${FILES[@]}"; do
  repo_path="${entry%%:*}"
  target_subdir="${entry##*:}"
  target_dir="$VOLUME_ROOT/$target_subdir"
  filename="$(basename "$repo_path")"

  mkdir -p "$target_dir"
  if [ -s "$target_dir/$filename" ]; then
    echo "SKIP  $filename (already present, $(du -h "$target_dir/$filename" | cut -f1))"
    continue
  fi

  echo "GET   $repo_path -> $target_dir/"
  # --local-dir with the repo's own nested path, then move the file up so
  # it lands flat in the folder ComfyUI scans (ComfyUI does not recurse
  # into the repo's directory structure).
  hf download "$REPO" "$repo_path" --local-dir "$target_dir/.hf_tmp" --token "$HF_TOKEN"
  mv "$target_dir/.hf_tmp/$repo_path" "$target_dir/$filename"
  rm -rf "$target_dir/.hf_tmp"
  echo "OK    $filename ($(du -h "$target_dir/$filename" | cut -f1))"
done

echo
echo "--- final layout ---"
for sub in models/diffusion_models models/text_encoders models/vae models/latent_upscale_models; do
  echo "$sub:"
  ls -lh "$VOLUME_ROOT/$sub" 2>/dev/null | tail -n +2 | awk '{print "   ", $9, $5}'
done

echo
echo "NEXT: extra_model_paths.yaml must map latent_upscale_models (added"
echo "      2026-09-01) and the worker image must be rebuilt/recycled to"
echo "      pick it up, or LatentUpscaleModelLoader will not see the file."

"""Self-hosted (RunPod Serverless + ComfyUI + LTX-2) counterpart to
app/services/culturetoon_video.py's Kling Omni path. Builds one LTX prompt
from a ToonScript's shots and resolves the cast's trained LoRA, then
submits the workflow to the RunPod Serverless inference endpoint
(app/media/runpod_serverless_client.py) — no pod lifecycle to manage here,
Serverless scales itself. DB writes and error handling live in
app/services/culturetoon_selfhosted_batch.py, the only caller.

Known simplification vs. the Kling Omni path: there's no equivalent to
Kling's multi-shot DSL (build_kling_prompt) here, so a script's shots are
folded into one continuous prompt rather than driving per-shot cuts — v1
produces one continuous clip. Also, ComfyUI's LoraLoader takes one LoRA per
generation, so a multi-character script's video is only grounded in the
PRIMARY (first-listed) cast member's trained identity; the rest are
described in the prompt text only, not visually locked in the way Kling
Omni's per-character Elements allow.
"""
import logging
from typing import Optional

logger = logging.getLogger("culturix.services.culturetoon_selfhosted_video")


class SelfHostedVideoGenerationError(Exception):
    pass


def build_prompt_from_script(script) -> str:
    """script: a ToonScript ORM object (shots/hook_line already populated).
    Folds hook_line + each shot's action/dialogue into one descriptive
    prompt string for a single continuous LTX generation."""
    parts = []
    if script.hook_line:
        parts.append(script.hook_line.strip())
    for shot in script.shots or []:
        action = (shot.get("action") or "").strip()
        dialogue = (shot.get("dialogue") or "").strip()
        if action:
            parts.append(action)
        if dialogue:
            parts.append(f'saying "{dialogue}"')
    return ". ".join(p for p in parts if p) or "A character reacts to their day."


def resolve_ready_lora(variants: list) -> str:
    """variants: the script's full cast (CharacterVariant ORM objects).
    Raises SelfHostedVideoGenerationError if ANY cast member's lora_status
    isn't "ready" — a script isn't generated with an inconsistent-looking
    character silently substituted in, same philosophy as
    generate_video_for_toon's own element_status check for Kling Omni.
    Returns the primary (first-listed) cast member's lora_path — see this
    module's docstring on the single-LoRA-per-generation limitation."""
    not_ready = [v.name for v in variants if v.lora_status != "ready"]
    if not_ready:
        raise SelfHostedVideoGenerationError(
            f"Character(s) not ready for self-hosted generation (no trained LoRA): {', '.join(not_ready)}"
        )
    return variants[0].lora_path


def generate_toon_video_selfhosted(script, variants: list, endpoint_id: str,
                                    duration_seconds: Optional[float] = None) -> bytes:
    """Returns raw video bytes for the caller to persist via
    app.media.storage.upload(). Raises SelfHostedVideoGenerationError (cast
    not ready) or whatever app.media.runpod_serverless_client/ltx_workflow
    raise on a Serverless-side failure."""
    from app.media import ltx_workflow, runpod_serverless_client

    lora_path = resolve_ready_lora(variants)
    prompt_text = build_prompt_from_script(script)
    total_duration = (
        duration_seconds
        or script.total_duration_seconds
        or sum(s.get("duration_seconds", 0) for s in (script.shots or []))
        or 5
    )

    workflow = ltx_workflow.build_workflow(prompt_text, total_duration, lora_path=lora_path)
    return runpod_serverless_client.run_inference_job(endpoint_id, workflow)

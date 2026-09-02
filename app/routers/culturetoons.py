"""CultureToons — Character-Based Posting, the 3rd Culturix product.

Data-management + generation API for a user's "toon accounts" (many per
user — Funny Clips, Baby Videos, Tech Updates, ... each with its own
character roster and connected social accounts, managed centrally): base
Characters, their cultural CharacterVariants (each registerable as a Kling
Element for cross-video character consistency), each variant's 10 reusable
Expressions (optional visual reference only, not a generation dependency),
reusable Backgrounds, punchy shot-structured ToonScripts (optionally
trend-tied and/or AI-suggested), and Toons — the production/posting tracker
linking a variant+script+background into one plannable clip, generated via
Kling 3.0 Omni (app/services/culturetoon_video.py) into one multi-shot video
plus 3-4 candidate clips.
"""
import logging
import os
import uuid as _uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks

logger = logging.getLogger("culturix.routers.culturetoons")
router = APIRouter(prefix="/api/culturetoons")

EXPRESSION_NAMES = [
    "Angry", "Confused", "Happy", "Shocked", "Laughing",
    "Side-eye", "Crying", "Annoyed", "Smiling", "Deadpan",
]
# Concrete facial-expression phrasing per name, for AI-generating an
# expression image (see generate_expression_image) — a few of these names
# ("Side-eye", "Deadpan") are common English idioms but not obviously
# unambiguous instructions for an image model on their own, so each gets a
# short, visually concrete cue instead of relying on the bare name alone.
EXPRESSION_PROMPT_HINTS = {
    "Angry": "an angry expression — furrowed brow, gritted teeth, glaring eyes",
    "Confused": "a confused expression — one eyebrow raised, tilted head, puzzled frown",
    "Happy": "a happy, cheerful expression — bright open smile, relaxed eyes",
    "Shocked": "a shocked expression — wide eyes, raised eyebrows, open mouth",
    "Laughing": "a laughing expression — eyes crinkled shut or nearly shut, wide open-mouth smile",
    "Side-eye": "a skeptical side-eye expression — eyes glancing sideways without turning the head, one eyebrow slightly raised, flat mouth",
    "Crying": "a crying expression — welling or streaming tears, downturned trembling mouth",
    "Annoyed": "an annoyed expression — narrowed eyes, tight flat mouth, slightly furrowed brow",
    "Smiling": "a warm, gentle smiling expression — soft closed-mouth or light smile, relaxed eyes",
    "Deadpan": "a deadpan expression — completely neutral, flat affect, no visible emotion, still front-facing",
}
TONE_OPTIONS = ["funny", "dramatic", "satiric", "sad", "wholesome", "chaotic", "deadpan"]

# Every character (and, by default, its variants) is illustrated in one of
# these styles. This exists because AI image generation with no explicit
# style instruction — even in this cartoon-focused product — tends to just
# lightly retouch a supplied reference photo instead of actually
# re-illustrating it (confirmed live: a real photo in, a near-identical
# photo out). _build_cartoon_prompt below is what forces the stylization.
ART_STYLES = {
    "cartoon_3d": {
        "label": "3D Pixar-style cartoon",
        "prompt": "a vibrant 3D Pixar/DreamWorks-style animated cartoon character, "
                  "exaggerated friendly proportions, smooth stylized shading, clean "
                  "character-turnaround studio lighting",
    },
    "anime": {
        "label": "2D anime style",
        "prompt": "a 2D anime-style character illustration, clean cel-shaded line art, "
                  "expressive anime facial features",
    },
    "flat_vector": {
        "label": "Flat vector illustration",
        "prompt": "a flat vector illustration character design, bold clean outlines, "
                  "simplified geometric shapes, solid flat colors, modern mascot-style design",
    },
    "claymation": {
        "label": "Claymation style",
        "prompt": "a claymation-style stop-motion character, sculpted clay texture, soft "
                  "rounded forms, subtle visible tool/fingerprint marks",
    },
    "cinematic_cultural": {
        "label": "Cinematic cultural (painterly)",
        "prompt": "a semi-realistic painterly digital illustration character, cinematic matte-"
                  "painting rendering, warm golden-hour lighting, rich saturated color grading, "
                  "detailed but stylized (not photoreal) — the same illustration technique used "
                  "for concept-art establishing shots",
    },
}
DEFAULT_ART_STYLE = "cartoon_3d"


def _validate_personality(personality: dict) -> None:
    """Light structural validation for Character.personality — see
    docs/culturix-comedy-architecture.md §3.2 for the shape. JSON, not
    DB-constrained, so this is the only guard against garbage shapes making
    it into the prompt builder later."""
    if not isinstance(personality, dict):
        raise HTTPException(status_code=400, detail="personality must be an object")
    allowed_keys = {"traits", "behavioral_rules", "speech_rules"}
    unknown = set(personality.keys()) - allowed_keys
    if unknown:
        raise HTTPException(status_code=400, detail=f"personality has unknown fields: {sorted(unknown)}")
    traits = personality.get("traits")
    if traits is not None:
        if not isinstance(traits, dict):
            raise HTTPException(status_code=400, detail="personality.traits must be an object of trait_name -> number")
        for name, value in traits.items():
            if not isinstance(name, str) or not isinstance(value, (int, float)) or isinstance(value, bool):
                raise HTTPException(status_code=400, detail=f"personality.traits.{name} must be a number")
            if not (0 <= value <= 1):
                raise HTTPException(status_code=400, detail=f"personality.traits.{name} must be between 0 and 1")
    for list_field in ("behavioral_rules", "speech_rules"):
        value = personality.get(list_field)
        if value is not None and (not isinstance(value, list) or not all(isinstance(v, str) for v in value)):
            raise HTTPException(status_code=400, detail=f"personality.{list_field} must be a list of strings")


def _build_cartoon_prompt(
    description: str, art_style_key: str, has_reference_image: bool,
    preserve_identity: bool = True, extra: str = "",
) -> str:
    """Confirmed live against Qwen-Image (see conversation notes, not
    committed to the repo): with a reference photo, the naive version of
    this prompt ("re-render in this style, don't just retouch the photo")
    only cartoonified the face and left the body/clothing/background
    photorealistic. Explicitly demanding a *different framing* than the
    reference photo (waist-up vs. whatever pose the photo has) is what
    actually breaks the image-to-image model's bias toward preserving the
    input's composition — asking for the "same" framing let it take a
    shortcut of lightly retouching the original pixels instead of properly
    re-illustrating them. The text-only path (no reference image) needs no
    such trick; a plain style instruction already produces a clean cartoon.

    preserve_identity=True (character's own photo, or a variant's own
    photo): ground on the reference's actual face/gender/skin tone — this
    IS that person.

    preserve_identity=False (a variant with no photo of its own, grounded
    on the base character's portrait purely for shared art style/roster
    consistency): a bare "ignore the reference's identity" instruction was
    tested live and reliably FAILED — Qwen-Image kept reproducing the same
    face/gender/body regardless of how explicitly the prompt said not to.
    What actually works, confirmed live: (1) frame it as "recasting the
    same role with a different actor" rather than "ignore identity", which
    keeps the model anchored on style/palette while still swapping the
    person, and (2) feed in a CONCRETE visual description (gender, age,
    ethnicity, face shape, hair — see _expand_variant_visual_description)
    rather than a vague relational one like "she is the wife of X", which
    on its own wasn't a strong enough visual anchor to consistently
    override the reference face."""
    style = ART_STYLES.get(art_style_key, ART_STYLES[DEFAULT_ART_STYLE])
    if has_reference_image and preserve_identity:
        grounding = (
            f"Redraw the person in the reference photo as {style['prompt']}, waist-up studio "
            "character portrait (a different framing and setting than the reference photo — do "
            "not copy its pose, background, or composition). Use the reference photo only to "
            "match facial identity, hairstyle, and skin tone — redraw everything else, including "
            "clothing and shading, as illustrated cartoon art rather than photographic texture. "
            "This must read as cartoon art, not a photograph."
        )
    elif has_reference_image:
        grounding = (
            f"Waist-up studio character portrait, {style['prompt']}, a different framing and "
            "setting than the reference image. Keep ONLY the reference image's art style, "
            "rendering technique, and color palette — as if this is a different character in the "
            "exact same animated show. Do NOT reuse the reference's face shape, eyes, nose, "
            "gender, ethnicity, or body — those must come entirely from the description below, "
            "even if that means a completely different-looking character. Think of this as "
            "recasting the same role with a different actor."
        )
    else:
        grounding = (
            f"Waist-up studio character portrait, {style['prompt']}. This must be a fully stylized, "
            "illustrated cartoon character, not a photorealistic photo. Consistent camera distance "
            "and framing matters — this portrait is later composited alongside other characters "
            "generated the same way, so an unusually close/cropped or unusually distant shot makes "
            "the character read as a mismatched size next to the others."
        )
    parts = [grounding, extra, description, "Centered, front-facing, single character, high detail illustration."]
    return " ".join(p for p in parts if p)


def _expand_variant_visual_description(character, variant, raw_description: str) -> tuple:
    """A variant's own description is often relational/vague ("she is the
    wife of Kumar, high society") rather than visually concrete — fine for
    a human reader, but confirmed live to be too weak an anchor to reliably
    override a grounding reference image's face/gender/ethnicity (the
    image model needs an explicit visual description to latch onto, not a
    relationship). Expands it into a concrete paragraph (gender, age,
    ethnicity/skin tone, face shape, hair, attire) via the same Qwen-max
    primary / Claude Haiku fallback pattern as culturetoon_script.py, used
    only to build the image prompt — the user's own raw_description is
    what's actually persisted/shown, this is never stored. Falls back to
    the raw description unchanged if the expansion call fails, so a
    provider outage degrades generation quality rather than blocking it —
    but confirmed live that silent degradation is a real trap: with no
    ethnicity/attire anchor at all, the image model is free to invent
    anything (confirmed producing a shirtless portrait with no clothing
    description ever requested). Returns (description, degraded) so the
    caller can surface that this generation is lower-confidence instead of
    the failure disappearing entirely."""
    prompt = f"""You are a character designer writing a concrete VISUAL description for an illustrator, based on a brief, possibly relational description of a character.

Base character: {character.name} - {character.description or "no description"}
This variant's name: {variant.name}
{"This variant's ethnicity/cultural background: " + variant.culture_tag if variant.culture_tag else ""}
User's brief description of this variant: "{raw_description}"

Write a single concrete paragraph (3-5 sentences) describing exactly what THIS VARIANT should look like: gender, approximate age, ethnicity/skin tone, face shape, hair color and style, and appropriate modest attire (invent reasonable attire if none is implied — never leave the character without clothing). Do not mention the base character, their name, or their relationship — describe ONLY this variant's own appearance, as if for an illustrator who will draw it without ever seeing the base character. Output plain text only, one paragraph, no headers, no meta-commentary."""
    try:
        if os.getenv("QWEN_API_KEY"):
            from openai import OpenAI
            qwen = OpenAI(api_key=os.environ["QWEN_API_KEY"], base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
            response = qwen.chat.completions.create(
                model="qwen-max", messages=[{"role": "user", "content": prompt}], temperature=0.7,
            )
            return response.choices[0].message.content.strip(), False
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        message = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip(), False
    except Exception:
        logger.warning("Variant visual-description expansion failed, using raw description", exc_info=True)
        return raw_description, True


# ── ownership / lookup helpers ───────────────────────────────────────────

def _get_brand_owned(session, brand_id: str, user_id: str):
    from app.models.character_brand import CharacterBrand
    brand = session.query(CharacterBrand).filter_by(id=_uuid.UUID(brand_id)).first()
    if not brand or brand.user_id != _uuid.UUID(user_id):
        raise HTTPException(status_code=404, detail="CultureToons brand not found")
    return brand


def _check_budget_or_raise(session, brand):
    """Call at the top of every route that's about to spend money on a
    generation (video, image, voice, Kling Element/voice registration) —
    before the provider call, not after. Returns a warning string (or None)
    for the caller to surface non-blockingly; raises 402 if the brand's
    budget is exhausted. A brand with no budget configured is never
    blocked — see app/services/culturetoon_usage.py::check_budget."""
    from app.services.culturetoon_usage import check_budget
    result = check_budget(session, brand)
    if result["blocked"]:
        raise HTTPException(status_code=402, detail=result["reason"])
    return result["warning"]


def _get_character_owned(session, character_id: str, brand_id: str, user_id: str):
    from app.models.character import Character
    _get_brand_owned(session, brand_id, user_id)
    character = session.query(Character).filter_by(id=_uuid.UUID(character_id)).first()
    if not character or str(character.brand_id) != brand_id:
        raise HTTPException(status_code=404, detail="Character not found")
    return character


def _get_variant_owned(session, variant_id: str, brand_id: str, user_id: str):
    from app.models.character_variant import CharacterVariant
    variant = session.query(CharacterVariant).filter_by(id=_uuid.UUID(variant_id)).first()
    if not variant:
        raise HTTPException(status_code=404, detail="Character variant not found")
    _get_character_owned(session, str(variant.character_id), brand_id, user_id)
    return variant


def _get_background_owned(session, background_id: str, brand_id: str, user_id: str):
    from app.models.toon_background import ToonBackground
    background = session.query(ToonBackground).filter_by(id=_uuid.UUID(background_id)).first()
    brand = _get_brand_owned(session, brand_id, user_id)
    if not background or background.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Background not found")
    return background


def _get_script_owned(session, script_id: str, brand_id: str, user_id: str):
    from app.models.toon_script import ToonScript
    script = session.query(ToonScript).filter_by(id=_uuid.UUID(script_id)).first()
    brand = _get_brand_owned(session, brand_id, user_id)
    if not script or script.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Script not found")
    return script


def _get_toon_owned(session, toon_id: str, brand_id: str, user_id: str):
    from app.models.toon import Toon
    toon = session.query(Toon).filter_by(id=_uuid.UUID(toon_id)).first()
    brand = _get_brand_owned(session, brand_id, user_id)
    if not toon or toon.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Toon not found")
    return toon


def _fetch_trend_source(session, source_type: str, source_id: int):
    if source_type == "persona":
        from app.models.persona import Persona
        return session.query(Persona).filter_by(id=source_id).first()
    from app.models.cluster import Cluster
    return session.query(Cluster).filter_by(id=source_id).first()


# ── serializers ───────────────────────────────────────────────────────────

def _serialize_brand(b) -> dict:
    return {
        "id": str(b.id), "user_id": str(b.user_id), "name": b.name,
        "description": b.description, "is_active": b.is_active,
        "target_platforms": b.target_platforms or [],
        "delivery_freq": b.delivery_freq, "delivery_time": b.delivery_time,
        "delivery_day_of_week": b.delivery_day_of_week,
        "has_elevenlabs_key": bool(b.elevenlabs_api_key_encrypted),
        "trend_interests": b.trend_interests,
        "daily_budget": float(b.daily_budget) if b.daily_budget is not None else None,
        "monthly_budget": float(b.monthly_budget) if b.monthly_budget is not None else None,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
    }


def _serialize_character(c) -> dict:
    return {
        "id": str(c.id), "brand_id": str(c.brand_id), "name": c.name,
        "description": c.description, "base_image_url": c.base_image_url,
        "reference_image_url": c.reference_image_url,
        "previous_image_urls": c.previous_image_urls or [],
        "art_style": c.art_style, "personality": c.personality,
        "is_active": c.is_active, "is_main": c.is_main,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _serialize_variant(v) -> dict:
    return {
        "id": str(v.id), "character_id": str(v.character_id), "name": v.name,
        "culture_tag": v.culture_tag, "culture_id": str(v.culture_id) if v.culture_id else None,
        "description": v.description,
        "image_url": v.image_url, "reference_image_url": v.reference_image_url,
        "previous_image_urls": v.previous_image_urls or [],
        "persona_id": v.persona_id, "is_active": v.is_active,
        "kling_element_id": v.kling_element_id, "kling_element_name": v.kling_element_name,
        "kling_voice_id": v.kling_voice_id, "element_status": v.element_status,
        "element_error": v.element_error,
        "voice_provider": v.voice_provider, "elevenlabs_voice_id": v.elevenlabs_voice_id,
        "lora_path": v.lora_path, "lora_status": v.lora_status, "lora_error": v.lora_error,
        "lora_training_images": v.lora_training_images or [],
        "lora_preview_url": v.lora_preview_url, "lora_preview_status": v.lora_preview_status,
        "lora_preview_error": v.lora_preview_error,
        "expressions_generating": v.expressions_generating,
        "expressions_generate_errors": v.expressions_generate_errors or {},
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


def _serialize_expression(e) -> dict:
    return {
        "id": str(e.id), "character_variant_id": str(e.character_variant_id),
        "name": e.name, "image_url": e.image_url,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _serialize_background(bg) -> dict:
    return {
        "id": str(bg.id), "brand_id": str(bg.brand_id), "name": bg.name,
        "image_url": bg.image_url, "tags": bg.tags, "description": bg.description,
        "country": bg.country, "visual_style": bg.visual_style,
        "reference_image_urls": bg.reference_image_urls or [],
        "is_active": bg.is_active,
        "created_at": bg.created_at.isoformat() if bg.created_at else None,
        "updated_at": bg.updated_at.isoformat() if bg.updated_at else None,
    }


def _serialize_script(s) -> dict:
    return {
        "id": str(s.id), "brand_id": str(s.brand_id),
        "character_variant_id": str(s.character_variant_id) if s.character_variant_id else None,
        "character_variant_ids": list(s.character_variant_ids) if s.character_variant_ids else [],
        "source_type": s.source_type, "source_id": s.source_id, "idea_text": s.idea_text,
        "hook_line": s.hook_line, "dialogue": s.dialogue, "scene_direction": s.scene_direction,
        "tone": s.tone, "shots": s.shots, "total_duration_seconds": s.total_duration_seconds,
        "comedy_judgment": s.comedy_judgment,
        "background_id": str(s.background_id) if s.background_id else None,
        "generation_source": s.generation_source, "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _script_scene_description(script) -> str:
    """The text a background should be generated from — a script's own
    scene setting, not something typed independently of it. scene_direction
    is used verbatim for manual scripts; AI-suggested (shot-structured)
    scripts have no single scene_direction, so their shots' action lines
    are concatenated instead (that's where "cut to the kitchen" / "outside
    on a balcony" style setting descriptions actually live for those)."""
    if script.scene_direction:
        return script.scene_direction.strip()
    if script.shots:
        actions = [s.get("action", "").strip() for s in script.shots if s.get("action")]
        if actions:
            return " ".join(actions)
    return ""


def _build_background_prompt(description: str, art_style_key: str) -> str:
    """Scene/setting illustration — deliberately NOT the same template as
    _build_cartoon_prompt: no reference-image identity handling (backgrounds
    are always generated from text only, never grounded on a photo), and
    explicitly excludes any character/person from the frame, since Kling
    composites the character element separately at video-generation time
    (see generate_video_for_toon) — a background with its own person in it
    would just be a second, uncontrolled character in the shot. Uses just
    the style's short label (e.g. "3D Pixar-style cartoon"), not its full
    character-oriented prompt fragment — that fragment's "character-
    turnaround" phrasing doesn't apply to a static scene."""
    style = ART_STYLES.get(art_style_key, ART_STYLES[DEFAULT_ART_STYLE])
    return (
        f"A background/setting illustration in the visual style of {style['label']}, wide "
        "establishing shot, smooth stylized shading and clean linework matching that style. "
        "This is an empty scene/environment only — no people, no characters, no figures anywhere in "
        f"the frame. Scene: {description}. Fully stylized illustrated background art, not a "
        "photorealistic photo. High detail, single continuous scene."
    )


def _serialize_toon(t) -> dict:
    return {
        "id": str(t.id), "brand_id": str(t.brand_id),
        "character_variant_id": str(t.character_variant_id),
        "script_id": str(t.script_id),
        "background_id": str(t.background_id) if t.background_id else None,
        "title": t.title, "final_video_url": t.final_video_url, "status": t.status,
        "platform": t.platform,
        "posted_at": t.posted_at.isoformat() if t.posted_at else None,
        "notes": t.notes,
        "raw_video_url": t.raw_video_url, "clip_video_urls": t.clip_video_urls or [],
        "previous_video_urls": t.previous_video_urls or [],
        "qa_results": t.qa_results, "publish_recommended": t.publish_recommended,
        "kling_task_id": t.kling_task_id, "generation_error": t.generation_error,
        "episode_id": str(t.episode_id) if t.episode_id else None, "part_order": t.part_order,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _get_toon_post_owned(session, toon_post_id: str, brand_id: str, user_id: str):
    from app.models.toon_post import ToonPost
    brand = _get_brand_owned(session, brand_id, user_id)
    post = session.query(ToonPost).filter_by(id=_uuid.UUID(toon_post_id)).first()
    if not post or post.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Toon post not found")
    return post


def _serialize_toon_post(p) -> dict:
    return {
        "id": str(p.id), "toon_id": str(p.toon_id), "brand_id": str(p.brand_id),
        "platform": p.platform, "post_url": p.post_url,
        "platform_post_id": p.platform_post_id, "status": p.status,
        "latest_views": p.latest_views, "latest_likes": p.latest_likes,
        "latest_comments": p.latest_comments, "latest_shares": p.latest_shares,
        "last_fetched_at": p.last_fetched_at.isoformat() if p.last_fetched_at else None,
        "error": p.error,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
    }


def _get_episode_owned(session, episode_id: str, brand_id: str, user_id: str):
    from app.models.toon_episode import ToonEpisode
    brand = _get_brand_owned(session, brand_id, user_id)
    episode = session.query(ToonEpisode).filter_by(id=_uuid.UUID(episode_id)).first()
    if not episode or episode.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Episode not found")
    return episode


def _serialize_episode(session, e) -> dict:
    from app.models.toon import Toon
    parts = (
        session.query(Toon)
        .filter_by(episode_id=e.id)
        .order_by(Toon.part_order.asc())
        .all()
    )
    return {
        "id": str(e.id), "brand_id": str(e.brand_id), "title": e.title, "status": e.status,
        "final_video_url": e.final_video_url, "clip_video_urls": e.clip_video_urls or [],
        "generation_error": e.generation_error,
        "parts": [
            {
                "toon_id": str(p.id), "order_index": p.part_order, "status": p.status,
                "title": p.title, "has_raw_video": bool(p.raw_video_url),
            }
            for p in parts
        ],
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _episode_synopsis(session, episode) -> str:
    """Builds the "what happened so far" text fed to
    generate_toon_script_continuing_episode — one line per existing part,
    made of that part's shots' dialogue/action beats (dialogue carries more
    continuity signal than action alone, so a shot with both leads with
    action then quotes the line; a silent shot falls back to its hook_line
    so a part never contributes an empty line)."""
    from app.models.toon import Toon
    from app.models.toon_script import ToonScript

    parts = (
        session.query(Toon).filter_by(episode_id=episode.id)
        .order_by(Toon.part_order.asc()).all()
    )
    lines = []
    for i, part in enumerate(parts, start=1):
        script = session.query(ToonScript).filter_by(id=part.script_id).first()
        if not script:
            continue
        beats = []
        for shot in (script.shots or []):
            action = (shot.get("action") or "").strip()
            dialogue = (shot.get("dialogue") or "").strip()
            if action and dialogue:
                beats.append(f'{action} — "{dialogue}"')
            elif dialogue:
                beats.append(f'"{dialogue}"')
            elif action:
                beats.append(action)
        summary = " ".join(beats) or (script.hook_line or "")
        lines.append(f"Part {i}: {summary}")
    return "\n".join(lines)


# ── brands ────────────────────────────────────────────────────────────────

@router.post("/brands")
def create_brand(body: dict):
    from app.db import SessionLocal
    from app.models.character_brand import CharacterBrand
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    session = SessionLocal()
    try:
        brand = CharacterBrand(
            user_id=_uuid.UUID(user_id),
            name=body.get("name", "My CultureToons Brand"),
            description=body.get("description"),
            target_platforms=body.get("target_platforms") or [],
            trend_interests=(body.get("trend_interests") or "").strip() or None,
        )
        session.add(brand)
        session.commit()
        session.refresh(brand)
        return _serialize_brand(brand)
    finally:
        session.close()


@router.get("/brands")
def list_brands(user_id: str, active_only: bool = True):
    from app.db import SessionLocal
    from app.models.character_brand import CharacterBrand
    session = SessionLocal()
    try:
        query = session.query(CharacterBrand).filter_by(user_id=_uuid.UUID(user_id))
        if active_only:
            query = query.filter_by(is_active=True)
        brands = query.order_by(CharacterBrand.created_at.asc()).all()
        return [_serialize_brand(b) for b in brands]
    finally:
        session.close()


@router.get("/brands/{brand_id}")
def get_brand(brand_id: str, user_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        return _serialize_brand(brand)
    finally:
        session.close()


@router.put("/brands/{brand_id}")
def update_brand(brand_id: str, body: dict):
    from app.db import SessionLocal
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        for field in ("name", "description", "is_active", "target_platforms",
                      "delivery_freq", "delivery_time", "delivery_day_of_week"):
            if field in body:
                setattr(brand, field, body[field])
        if "trend_interests" in body:
            new_value = (body["trend_interests"] or "").strip() or None
            if new_value != brand.trend_interests:
                # Stale cache would rank against the OLD interests text —
                # clear it so get_interests_embedding recomputes on next use.
                brand.trend_interests_embedding = None
            brand.trend_interests = new_value
        for budget_field in ("daily_budget", "monthly_budget"):
            if budget_field in body:
                value = body[budget_field]
                if value is not None:
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=400, detail=f"{budget_field} must be a number or null")
                    if value < 0:
                        raise HTTPException(status_code=400, detail=f"{budget_field} must be >= 0")
                setattr(brand, budget_field, value)
        if "elevenlabs_api_key" in body:
            from app.social.crypto import encrypt
            raw_key = body["elevenlabs_api_key"]
            brand.elevenlabs_api_key_encrypted = encrypt(raw_key) if raw_key else None
        session.commit()
        session.refresh(brand)
        return _serialize_brand(brand)
    finally:
        session.close()


@router.get("/trend-sources")
def get_trend_sources(user_id: str, brand_id: str):
    """Personas/clusters for the Scripts tab's "Suggest a script from a
    trend" picker — ranked by relevance to the brand's own trend_interests
    when set (see app/services/culturetoon_trend_relevance.py), otherwise
    the same recent unfiltered feed as before this existed. Replaces the
    old approach of the Next.js proxy route aggregating the trend engine's
    generic /personas and /clusters endpoints directly with no brand
    awareness at all."""
    from app.db import SessionLocal
    from app.models.persona import Persona
    from app.models.cluster import Cluster

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        personas = (
            session.query(Persona).filter(Persona.status == "active")
            .order_by(Persona.updated_at.desc()).limit(50).all()
        )
        clusters = (
            session.query(Cluster).order_by(Cluster.updated_at.desc()).limit(50).all()
        )

        personalized = False
        if brand.trend_interests:
            try:
                from app.services.culturetoon_trend_relevance import get_interests_embedding, rank_by_relevance
                interests_embedding = get_interests_embedding(brand)
                personas = rank_by_relevance(
                    session, personas, lambda p: f"{p.name}. {p.description}", interests_embedding,
                )[:15]
                clusters = rank_by_relevance(
                    session, clusters, lambda c: f"{c.theme or ''}. {c.summary or ''}", interests_embedding,
                )[:15]
                personalized = True
                session.commit()
            except Exception:
                session.rollback()
                logging.getLogger("culturix.routers.culturetoons").warning(
                    "Trend relevance ranking failed for brand %s, falling back to unfiltered list", brand_id, exc_info=True,
                )
                personas = personas[:15]
                clusters = clusters[:15]
        else:
            personas = personas[:15]
            clusters = clusters[:15]

        return {
            "personalized": personalized,
            "personas": [{"id": p.id, "name": p.name, "description": p.description} for p in personas],
            "clusters": [{"id": c.id, "name": c.theme or f"Cluster {c.id}", "description": c.summary} for c in clusters],
        }
    finally:
        session.close()


@router.get("/brands/{brand_id}/usage")
def get_brand_usage(brand_id: str, user_id: str):
    """Surfaces generation_usage spend for the Usage & Budget panel — see
    app/services/culturetoon_usage.py. cost_usd can be NULL for
    not-yet-priced generations (Qwen-Image fallback tier, most notably), so
    daily_spend/monthly_spend here are a floor, not a ceiling, on actual
    spend — see that module's docstring."""
    from app.db import SessionLocal
    from datetime import datetime as _datetime
    from sqlalchemy import func
    from app.models.generation_usage import GenerationUsage
    from app.services.culturetoon_usage import check_budget

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        budget_status = check_budget(session, brand)

        month_start = _datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        by_type = (
            session.query(
                GenerationUsage.generation_type,
                func.count(GenerationUsage.id),
                func.coalesce(func.sum(GenerationUsage.cost_usd), 0),
            )
            .filter(GenerationUsage.brand_id == brand.id, GenerationUsage.created_at >= month_start)
            .group_by(GenerationUsage.generation_type)
            .all()
        )
        untyped_count = (
            session.query(func.count(GenerationUsage.id))
            .filter(
                GenerationUsage.brand_id == brand.id,
                GenerationUsage.created_at >= month_start,
                GenerationUsage.cost_usd.is_(None),
            )
            .scalar()
        )
        return {
            "daily_budget": float(brand.daily_budget) if brand.daily_budget is not None else None,
            "monthly_budget": float(brand.monthly_budget) if brand.monthly_budget is not None else None,
            "daily_spend": float(budget_status["daily_spend"]),
            "monthly_spend": float(budget_status["monthly_spend"]),
            "warning": budget_status["warning"],
            "this_month_by_type": [
                {"generation_type": t, "count": c, "cost_usd": float(cost)} for t, c, cost in by_type
            ],
            "unpriced_generations_this_month": untyped_count or 0,
        }
    finally:
        session.close()


# ── characters ────────────────────────────────────────────────────────────

@router.post("/characters")
def create_character(body: dict):
    from app.db import SessionLocal
    from app.models.character import Character
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id or not body.get("name"):
        raise HTTPException(status_code=400, detail="user_id, brand_id and name are required")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        art_style = body.get("art_style") or DEFAULT_ART_STYLE
        if art_style not in ART_STYLES:
            raise HTTPException(status_code=400, detail=f"Unknown art_style: {art_style}")
        # The brand's first character automatically becomes its main
        # character — no user action required, since there's no one else
        # yet for "main" to mean anything relative to. Once a brand has a
        # cast, defaulting every next character to non-main would be the
        # obviously right call too, EXCEPT the previous version of this
        # endpoint didn't allow the caller to override that guess at all —
        # confirmed live to actually happen: a character created first
        # (before, say, "Suggest a cast" adds the character the creator
        # actually intended as the lead) silently locked in as main with
        # no way to declare intent at creation time, only to notice and
        # fix it afterward via the star button. is_main is now honored
        # from the request when explicitly provided, falling back to the
        # first-character default otherwise.
        has_existing_character = session.query(Character.id).filter(
            Character.brand_id == brand.id, Character.is_active.is_(True),
        ).first() is not None
        is_main = bool(body["is_main"]) if "is_main" in body else not has_existing_character
        if is_main:
            # Same at-most-one-main invariant as PUT /characters/{id}.
            session.query(Character).filter(Character.brand_id == brand.id).update({"is_main": False})
        character = Character(
            brand_id=brand.id, name=body["name"], description=body.get("description"),
            art_style=art_style, is_main=is_main,
        )
        session.add(character)
        session.commit()
        session.refresh(character)

        # A bare Character has nowhere to be registered as a Kling element —
        # element_status/kling_element_id all live on CharacterVariant, never
        # on Character itself, so a character with zero variants has no
        # "Register for video" step reachable anywhere in the UI at all.
        # Confirmed live: this produced a genuinely stuck user ("no place to
        # register Kumar") who had no way to know a variant — even one just
        # representing the character itself — was a required extra step.
        # Auto-creating one named after the character removes that step
        # entirely for the common "just use this character as-is" case,
        # while named cultural variants remain fully optional additions.
        from app.models.character_variant import CharacterVariant
        default_variant = CharacterVariant(character_id=character.id, name=character.name[:120])
        session.add(default_variant)
        session.commit()
        session.refresh(default_variant)

        return {**_serialize_character(character), "default_variant": _serialize_variant(default_variant)}
    finally:
        session.close()


@router.post("/brands/{brand_id}/cast/generate")
def generate_cast(brand_id: str, body: dict):
    """AI-drafts a whole cast (characters + the relationships between them)
    from one free-text description of the show — see
    app/services/culturetoon_cast.py. Returns a draft only, never
    persisted — CastPlanWizard.tsx lets the user edit/exclude before
    actually creating anything via the existing POST /characters, PUT
    /characters/{id}, and POST /relationships routes."""
    from app.db import SessionLocal
    from app.models.character import Character
    from app.services.culturetoon_cast import generate_cast_plan, CastGenerationError

    user_id = body.get("user_id")
    plan_description = body.get("plan_description")
    if not user_id or not plan_description:
        raise HTTPException(status_code=400, detail="user_id and plan_description are required")

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        existing_names = [
            name for (name,) in session.query(Character.name).filter(
                Character.brand_id == brand.id, Character.is_active.is_(True),
            ).all()
        ]
        try:
            return generate_cast_plan(plan_description, existing_character_names=existing_names)
        except CastGenerationError as exc:
            raise HTTPException(status_code=502, detail=f"Cast generation failed: {exc}")
    finally:
        session.close()


@router.get("/characters")
def list_characters(user_id: str, brand_id: str, active_only: bool = True):
    from app.db import SessionLocal
    from app.models.character import Character
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        query = session.query(Character).filter_by(brand_id=brand.id)
        if active_only:
            query = query.filter_by(is_active=True)
        characters = query.order_by(Character.created_at.asc()).all()
        return [_serialize_character(c) for c in characters]
    finally:
        session.close()


@router.put("/characters/{character_id}")
def update_character(character_id: str, body: dict):
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        character = _get_character_owned(session, character_id, brand_id, user_id)
        if "art_style" in body and body["art_style"] not in ART_STYLES:
            raise HTTPException(status_code=400, detail=f"Unknown art_style: {body['art_style']}")
        if "personality" in body and body["personality"] is not None:
            _validate_personality(body["personality"])
        if body.get("is_main"):
            # At most one main character per brand — reassigning clears the
            # flag on whichever character had it before, enforced here
            # rather than trusted from the frontend.
            from app.models.character import Character
            session.query(Character).filter(
                Character.brand_id == character.brand_id, Character.id != character.id,
            ).update({"is_main": False})
        for field in ("name", "description", "is_active", "art_style", "personality", "is_main"):
            if field in body:
                setattr(character, field, body[field])
        session.commit()
        session.refresh(character)
        return _serialize_character(character)
    finally:
        session.close()


@router.post("/characters/{character_id}/personality/generate")
def generate_character_personality_draft(character_id: str, body: dict):
    """AI-drafts traits/behavioral_rules/speech_rules from the character's
    existing name/description/art_style plus an optional free-text hint —
    see app/services/culturetoon_personality.py. Returns a draft only, never
    persisted, so the user can review/tweak the pre-filled sliders before
    saving via the existing PUT /characters/{id} — same never-silently-
    overwrite contract as POST /relationships/generate."""
    from app.db import SessionLocal
    from app.services.culturetoon_personality import generate_character_personality, PersonalityGenerationError

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    hint = body.get("hint") or ""
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        character = _get_character_owned(session, character_id, brand_id, user_id)
        try:
            return generate_character_personality(character, hint=hint)
        except PersonalityGenerationError as exc:
            raise HTTPException(status_code=502, detail=f"Personality generation failed: {exc}")
    finally:
        session.close()


@router.delete("/characters/{character_id}")
def delete_character(character_id: str, user_id: str, brand_id: str):
    """Soft-delete, same pattern as delete_background: flips is_active off
    rather than removing the row, so existing scripts/toons/variants that
    still reference this character keep working. list_characters already
    filters to active_only=True by default, so this is enough to make the
    character disappear from the roster."""
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        character = _get_character_owned(session, character_id, brand_id, user_id)
        character.is_active = False
        session.commit()
        return {"status": "deactivated"}
    finally:
        session.close()


# ── relationships ────────────────────────────────────────────────────────
# Character-level, not CharacterVariant-level — see
# docs/culturix-comedy-architecture.md §3.4/decision 5. Directional
# refinement (2026-08): personality toward another character is not
# necessarily symmetrical, so per-direction affection/trust/conflict/
# perspective/behavior now live on CharacterRelationshipDirection (exactly
# two rows per relationship — see that model's docstring), while
# CharacterRelationship itself stays the single record for the pair
# (relationship type, general description, comedy_chemistry). The
# relationship's own affection_level/trust_level/conflict_level/
# behavioral_rules fields are kept for backward compatibility (existing
# rows, CharacterRelationshipEvent's delta application below) — see
# CharacterRelationship's class docstring.

_RELATIONSHIP_TYPES = {
    "friends": "Friends",
    "best_friends": "Best Friends",
    "friendly_rivalry": "Friendly Rivalry",
    "rivals": "Rivals",
    "coworkers": "Coworkers",
    "boss_employee": "Boss / Employee",
    "husband_wife": "Husband & Wife",
    "parent_child": "Parent & Child",
    "siblings": "Siblings",
    "neighbors": "Neighbors",
    "acquaintances": "Acquaintances",
    "mentor_student": "Mentor & Student",
    "enemies": "Enemies",
    "custom": "Custom",
}


def _validate_relationship_type(body: dict) -> tuple:
    """Returns (relationship_type, relationship_type_label). Both None if
    relationship_type wasn't provided at all (still optional, same as
    before this refinement). relationship_type_label defaults to the
    enum's own canonical label, or must be explicitly given when
    relationship_type is "custom"."""
    rtype = body.get("relationship_type")
    if rtype is None:
        return None, None
    if rtype not in _RELATIONSHIP_TYPES:
        raise HTTPException(status_code=400, detail=f"relationship_type must be one of {list(_RELATIONSHIP_TYPES)}")
    custom_label = (body.get("relationship_type_label") or "").strip()
    if rtype == "custom" and not custom_label:
        raise HTTPException(status_code=400, detail="relationship_type_label is required when relationship_type is 'custom'")
    return rtype, custom_label or _RELATIONSHIP_TYPES[rtype]


def _get_or_create_relationship_directions(session, relationship) -> list:
    """Returns [character_a->b direction, character_b->a direction],
    creating whichever are missing. A relationship created before this
    directional refinement has none yet — rather than showing empty
    dynamics for it (silently dropping data the user already entered),
    freshly-created directions are seeded from the relationship's own
    legacy symmetric fields (same affection/trust/conflict copied into
    both, behavioral_rules copied into both directions' rule sets) so
    existing functionality doesn't regress on first read after migration.
    The user can then let each direction diverge going forward."""
    from app.models.character_relationship_direction import CharacterRelationshipDirection
    from app.models.character_relationship_behavior_rule import CharacterRelationshipBehaviorRule

    existing = (
        session.query(CharacterRelationshipDirection)
        .filter_by(relationship_id=relationship.id).all()
    )
    by_from = {str(d.from_character_id): d for d in existing}
    a_id, b_id = str(relationship.character_a_id), str(relationship.character_b_id)
    created_any = False
    for from_id, to_id in ((a_id, b_id), (b_id, a_id)):
        if from_id in by_from:
            continue
        direction = CharacterRelationshipDirection(
            relationship_id=relationship.id, brand_id=relationship.brand_id,
            from_character_id=_uuid.UUID(from_id), to_character_id=_uuid.UUID(to_id),
            affection_level=relationship.affection_level, trust_level=relationship.trust_level,
            conflict_level=relationship.conflict_level,
        )
        session.add(direction)
        session.flush()
        for rule_text in (relationship.behavioral_rules or []):
            session.add(CharacterRelationshipBehaviorRule(
                relationship_direction_id=direction.id, brand_id=relationship.brand_id, rule_text=rule_text,
            ))
        by_from[from_id] = direction
        created_any = True
    if created_any:
        session.flush()
    return [by_from[a_id], by_from[b_id]]


def _serialize_relationship_direction(session, d) -> dict:
    from app.models.character_relationship_behavior_rule import CharacterRelationshipBehaviorRule
    rules = (
        session.query(CharacterRelationshipBehaviorRule)
        .filter_by(relationship_direction_id=d.id)
        .order_by(CharacterRelationshipBehaviorRule.created_at.asc()).all()
    )
    return {
        "id": str(d.id), "relationship_id": str(d.relationship_id),
        "from_character_id": str(d.from_character_id), "to_character_id": str(d.to_character_id),
        "affection_level": d.affection_level, "trust_level": d.trust_level, "conflict_level": d.conflict_level,
        "perspective_description": d.perspective_description,
        "behavior_rules": [r.rule_text for r in rules],
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _apply_direction_data(session, direction, data: Optional[dict]) -> None:
    """data: optional dict with any subset of affection_level/trust_level/
    conflict_level/perspective_description/behavior_rules (list[str]).
    behavior_rules, when provided, replaces the whole set for this
    direction (delete + reinsert) — same whole-list-replace semantics the
    old CharacterRelationship.behavioral_rules array column had, just
    structured records now instead of a single array."""
    if not data:
        return
    for level_field in ("affection_level", "trust_level", "conflict_level"):
        if data.get(level_field) is not None:
            value = int(data[level_field])
            if not (0 <= value <= 10):
                raise HTTPException(status_code=400, detail=f"{level_field} must be between 0 and 10")
            setattr(direction, level_field, value)
    if "perspective_description" in data:
        direction.perspective_description = data["perspective_description"]
    if "behavior_rules" in data:
        from app.models.character_relationship_behavior_rule import CharacterRelationshipBehaviorRule
        session.query(CharacterRelationshipBehaviorRule).filter_by(relationship_direction_id=direction.id).delete()
        for rule_text in (data.get("behavior_rules") or []):
            text = str(rule_text).strip()
            if text:
                session.add(CharacterRelationshipBehaviorRule(
                    relationship_direction_id=direction.id, brand_id=direction.brand_id, rule_text=text,
                ))


def _episode_character_map(session, brand_id) -> dict:
    """episode_id (str) -> set of character_id (str) present in that
    episode, via either Toon-parts or ToonScenes — used for the
    Relationship Library's "episodes together" count (section 7). Built
    once per list_relationships call rather than per-relationship."""
    from app.models.toon import Toon
    from app.models.toon_scene import ToonScene
    from app.models.character_variant import CharacterVariant
    from app.models.character import Character

    variant_rows = (
        session.query(CharacterVariant.id, CharacterVariant.character_id)
        .join(Character, Character.id == CharacterVariant.character_id)
        .filter(Character.brand_id == _uuid.UUID(str(brand_id))).all()
    )
    variant_to_character = {str(vid): str(cid) for vid, cid in variant_rows}

    episode_map: dict = {}
    parts = (
        session.query(Toon.episode_id, Toon.character_variant_id)
        .filter(Toon.brand_id == _uuid.UUID(str(brand_id)), Toon.episode_id.isnot(None)).all()
    )
    for episode_id, variant_id in parts:
        cid = variant_to_character.get(str(variant_id))
        if cid:
            episode_map.setdefault(str(episode_id), set()).add(cid)

    scenes = (
        session.query(ToonScene.episode_id, ToonScene.character_variant_ids)
        .filter(ToonScene.brand_id == _uuid.UUID(str(brand_id))).all()
    )
    for episode_id, variant_ids in scenes:
        for vid in (variant_ids or []):
            cid = variant_to_character.get(str(vid))
            if cid:
                episode_map.setdefault(str(episode_id), set()).add(cid)
    return episode_map


def _episodes_together_count(episode_map: dict, character_a_id, character_b_id) -> int:
    a, b = str(character_a_id), str(character_b_id)
    return sum(1 for chars in episode_map.values() if a in chars and b in chars)


def _serialize_relationship(session, r, episodes_together: int = 0) -> dict:
    directions = _get_or_create_relationship_directions(session, r)
    return {
        "id": str(r.id), "brand_id": str(r.brand_id),
        "character_a_id": str(r.character_a_id), "character_b_id": str(r.character_b_id),
        "relationship_type": r.relationship_type, "relationship_type_label": r.relationship_type_label,
        "description": r.description,
        "comedy_chemistry": r.comedy_chemistry,
        # Legacy symmetric fields — kept for backward compatibility, see
        # CharacterRelationship's class docstring. New code should read
        # "directions" instead.
        "emotional_dynamic": r.emotional_dynamic,
        "conflict_level": r.conflict_level, "trust_level": r.trust_level,
        "affection_level": r.affection_level,
        "humor_dynamic": r.humor_dynamic, "behavioral_rules": r.behavioral_rules or [],
        "directions": [_serialize_relationship_direction(session, d) for d in directions],
        "episodes_together": episodes_together,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.post("/relationships")
def create_relationship(body: dict):
    from app.db import SessionLocal
    from app.models.character_relationship import CharacterRelationship
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    character_a_id, character_b_id = body.get("character_a_id"), body.get("character_b_id")
    if not user_id or not brand_id or not character_a_id or not character_b_id:
        raise HTTPException(status_code=400, detail="user_id, brand_id, character_a_id and character_b_id are required")
    if character_a_id == character_b_id:
        raise HTTPException(status_code=400, detail="character_a_id and character_b_id must be different characters")
    relationship_type, relationship_type_label = _validate_relationship_type(body)
    if body.get("comedy_chemistry") is not None and not (0 <= int(body["comedy_chemistry"]) <= 10):
        raise HTTPException(status_code=400, detail="comedy_chemistry must be between 0 and 10")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        _get_character_owned(session, character_a_id, brand_id, user_id)
        _get_character_owned(session, character_b_id, brand_id, user_id)
        for level_field in ("conflict_level", "trust_level", "affection_level"):
            if body.get(level_field) is not None and not (0 <= int(body[level_field]) <= 10):
                raise HTTPException(status_code=400, detail=f"{level_field} must be between 0 and 10")
        relationship = CharacterRelationship(
            brand_id=brand.id,
            character_a_id=_uuid.UUID(character_a_id), character_b_id=_uuid.UUID(character_b_id),
            relationship_type=relationship_type, relationship_type_label=relationship_type_label,
            description=body.get("description"), comedy_chemistry=body.get("comedy_chemistry"),
            emotional_dynamic=body.get("emotional_dynamic"),
            conflict_level=body.get("conflict_level"), trust_level=body.get("trust_level"),
            affection_level=body.get("affection_level"),
            humor_dynamic=body.get("humor_dynamic"), behavioral_rules=body.get("behavioral_rules"),
        )
        session.add(relationship)
        session.flush()
        directions = _get_or_create_relationship_directions(session, relationship)
        directions_by_from = {str(d.from_character_id): d for d in directions}
        _apply_direction_data(session, directions_by_from[str(relationship.character_a_id)], body.get("a_to_b"))
        _apply_direction_data(session, directions_by_from[str(relationship.character_b_id)], body.get("b_to_a"))
        session.commit()
        session.refresh(relationship)
        return _serialize_relationship(session, relationship, episodes_together=0)
    finally:
        session.close()


@router.post("/relationships/generate")
def generate_relationship(body: dict):
    """AI-drafts relationship_type/description/comedy_chemistry/both
    directions' dynamics from the two characters' existing personality,
    culture, speech style and behavioral DNA — see
    app/services/culturetoon_relationship.py. Returns a draft only, never
    persisted, so the user can edit before saving (POST /relationships or
    PUT an existing one) — an existing relationship's data is never
    overwritten by this call."""
    from app.db import SessionLocal
    from app.models.character_variant import CharacterVariant
    from app.services.culturetoon_relationship import generate_relationship_dynamic, RelationshipGenerationError

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    character_a_id, character_b_id = body.get("character_a_id"), body.get("character_b_id")
    hint = body.get("hint") or ""
    if not user_id or not brand_id or not character_a_id or not character_b_id:
        raise HTTPException(status_code=400, detail="user_id, brand_id, character_a_id and character_b_id are required")
    if character_a_id == character_b_id:
        raise HTTPException(status_code=400, detail="character_a_id and character_b_id must be different characters")

    session = SessionLocal()
    try:
        _get_brand_owned(session, brand_id, user_id)
        character_a = _get_character_owned(session, character_a_id, brand_id, user_id)
        character_b = _get_character_owned(session, character_b_id, brand_id, user_id)

        def _culture_summary(character_id):
            tags = (
                session.query(CharacterVariant.culture_tag)
                .filter(CharacterVariant.character_id == character_id, CharacterVariant.culture_tag.isnot(None))
                .distinct().all()
            )
            return ", ".join(t[0] for t in tags if t[0])

        try:
            return generate_relationship_dynamic(
                character_a, character_b,
                culture_a=_culture_summary(character_a.id), culture_b=_culture_summary(character_b.id),
                hint=hint,
            )
        except RelationshipGenerationError as exc:
            raise HTTPException(status_code=502, detail=f"Relationship generation failed: {exc}")
    finally:
        session.close()


@router.post("/characters/{character_id}/relationships/suggest-with-cast")
def suggest_relationships_with_cast(character_id: str, body: dict):
    """For a character that wasn't part of an AI-suggested cast batch (e.g.
    created via the manual 'Create character' flow, or added after
    "Suggest a cast" already ran) — drafts a relationship between it and
    EVERY other active character in the brand, one AI call per pair, reusing
    generate_relationship_dynamic exactly like /relationships/generate does
    for a single pair. Cast-suggestion itself never recalibrates anything
    after the fact (see generate_cast_plan's own docstring) — this is the
    explicit, opt-in way to catch a character up on the relationships it
    would have gotten if it'd been in the original batch.

    Returns a list of drafts only, never persisted — same contract as
    every other AI-draft endpoint in this file. The caller reviews/selects
    which to keep and POSTs each to /relationships individually. One pair's
    generation failure doesn't block the rest — a per-item "error" field
    is included in the drafts list wherever that happened, rather than
    502ing the whole request for one bad pair."""
    from app.db import SessionLocal
    from app.models.character import Character
    from app.models.character_variant import CharacterVariant
    from app.services.culturetoon_relationship import generate_relationship_dynamic, RelationshipGenerationError

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        new_character = _get_character_owned(session, character_id, brand_id, user_id)

        others = (
            session.query(Character)
            .filter(Character.brand_id == brand.id, Character.is_active.is_(True), Character.id != new_character.id)
            .order_by(Character.created_at.asc())
            .all()
        )

        def _culture_summary(char_id):
            tags = (
                session.query(CharacterVariant.culture_tag)
                .filter(CharacterVariant.character_id == char_id, CharacterVariant.culture_tag.isnot(None))
                .distinct().all()
            )
            return ", ".join(t[0] for t in tags if t[0])

        culture_new = _culture_summary(new_character.id)
        drafts = []
        for other in others:
            try:
                draft = generate_relationship_dynamic(
                    new_character, other,
                    culture_a=culture_new, culture_b=_culture_summary(other.id),
                )
                drafts.append({
                    "character_a_id": str(new_character.id), "character_b_id": str(other.id),
                    "character_b_name": other.name, **draft,
                })
            except RelationshipGenerationError as exc:
                drafts.append({
                    "character_a_id": str(new_character.id), "character_b_id": str(other.id),
                    "character_b_name": other.name, "error": str(exc),
                })
        return drafts
    finally:
        session.close()


@router.get("/relationships")
def list_relationships(user_id: str, brand_id: str, character_id: Optional[str] = None, active_only: bool = True):
    from app.db import SessionLocal
    from app.models.character_relationship import CharacterRelationship
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        query = session.query(CharacterRelationship).filter_by(brand_id=brand.id)
        if active_only:
            query = query.filter_by(is_active=True)
        if character_id:
            cid = _uuid.UUID(character_id)
            query = query.filter(
                (CharacterRelationship.character_a_id == cid) | (CharacterRelationship.character_b_id == cid)
            )
        relationships = query.order_by(CharacterRelationship.created_at.asc()).all()
        episode_map = _episode_character_map(session, brand.id)
        return [
            _serialize_relationship(session, r, episodes_together=_episodes_together_count(episode_map, r.character_a_id, r.character_b_id))
            for r in relationships
        ]
    finally:
        session.close()


def _get_relationship_owned(session, relationship_id: str, brand_id: str, user_id: str):
    from app.models.character_relationship import CharacterRelationship
    brand = _get_brand_owned(session, brand_id, user_id)
    relationship = session.query(CharacterRelationship).filter_by(id=_uuid.UUID(relationship_id)).first()
    if not relationship or relationship.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Relationship not found")
    return relationship


@router.put("/relationships/{relationship_id}")
def update_relationship(relationship_id: str, body: dict):
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    relationship_type, relationship_type_label = _validate_relationship_type(body)
    if body.get("comedy_chemistry") is not None and not (0 <= int(body["comedy_chemistry"]) <= 10):
        raise HTTPException(status_code=400, detail="comedy_chemistry must be between 0 and 10")
    session = SessionLocal()
    try:
        relationship = _get_relationship_owned(session, relationship_id, brand_id, user_id)
        for level_field in ("conflict_level", "trust_level", "affection_level"):
            if body.get(level_field) is not None and not (0 <= int(body[level_field]) <= 10):
                raise HTTPException(status_code=400, detail=f"{level_field} must be between 0 and 10")
        if relationship_type is not None:
            relationship.relationship_type = relationship_type
            relationship.relationship_type_label = relationship_type_label
        for field in ("description", "emotional_dynamic", "conflict_level", "trust_level",
                      "affection_level", "humor_dynamic", "behavioral_rules", "is_active", "comedy_chemistry"):
            if field in body:
                setattr(relationship, field, body[field])

        if "a_to_b" in body or "b_to_a" in body:
            directions = _get_or_create_relationship_directions(session, relationship)
            directions_by_from = {str(d.from_character_id): d for d in directions}
            if "a_to_b" in body:
                _apply_direction_data(session, directions_by_from[str(relationship.character_a_id)], body.get("a_to_b"))
            if "b_to_a" in body:
                _apply_direction_data(session, directions_by_from[str(relationship.character_b_id)], body.get("b_to_a"))

        session.commit()
        session.refresh(relationship)
        episode_map = _episode_character_map(session, relationship.brand_id)
        episodes_together = _episodes_together_count(episode_map, relationship.character_a_id, relationship.character_b_id)
        return _serialize_relationship(session, relationship, episodes_together=episodes_together)
    finally:
        session.close()


@router.delete("/relationships/{relationship_id}")
def delete_relationship(relationship_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        relationship = _get_relationship_owned(session, relationship_id, brand_id, user_id)
        relationship.is_active = False
        session.commit()
        return {"status": "deactivated"}
    finally:
        session.close()


# ── relationship history (events) ───────────────────────────────────────
# A chronological log of what actually happened between two characters,
# distinct from the relationship's own static current-state fields — see
# app/models/character_relationship_event.py.

_RELATIONSHIP_EVENT_TYPES = [
    "conflict", "bonding", "running_joke", "betrayal", "reconciliation", "milestone", "general",
]
_RECENT_EVENTS_FOR_SCRIPT_CONTEXT = 3


def _serialize_relationship_event(e) -> dict:
    return {
        "id": str(e.id), "relationship_id": str(e.relationship_id), "brand_id": str(e.brand_id),
        "event_type": e.event_type, "description": e.description,
        "affection_delta": e.affection_delta, "trust_delta": e.trust_delta, "conflict_delta": e.conflict_delta,
        "source_toon_id": str(e.source_toon_id) if e.source_toon_id else None,
        "source_episode_id": str(e.source_episode_id) if e.source_episode_id else None,
        "source_scene_id": str(e.source_scene_id) if e.source_scene_id else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _apply_relationship_deltas(relationship, affection_delta, trust_delta, conflict_delta) -> None:
    """Nudges the relationship's current-state levels by the given deltas,
    clamped to 0-10 — applied once at event creation so a logged event is
    consequential, not just narrative flavor. See CharacterRelationshipEvent's
    docstring on why this isn't reversed on delete."""
    for field, delta in (("affection_level", affection_delta), ("trust_level", trust_delta), ("conflict_level", conflict_delta)):
        if delta:
            current = getattr(relationship, field) if getattr(relationship, field) is not None else 5
            setattr(relationship, field, max(0, min(10, current + delta)))


@router.post("/relationships/{relationship_id}/events")
def create_relationship_event(relationship_id: str, body: dict):
    from app.db import SessionLocal
    from app.models.character_relationship_event import CharacterRelationshipEvent

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    event_type = body.get("event_type")
    description = (body.get("description") or "").strip()
    if not user_id or not brand_id or not description:
        raise HTTPException(status_code=400, detail="user_id, brand_id and description are required")
    if event_type not in _RELATIONSHIP_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"event_type must be one of {_RELATIONSHIP_EVENT_TYPES}")
    deltas = {}
    for field in ("affection_delta", "trust_delta", "conflict_delta"):
        value = body.get(field)
        if value is not None:
            if not (-10 <= int(value) <= 10):
                raise HTTPException(status_code=400, detail=f"{field} must be between -10 and 10")
            deltas[field] = int(value)

    session = SessionLocal()
    try:
        relationship = _get_relationship_owned(session, relationship_id, brand_id, user_id)
        source_toon_id = body.get("source_toon_id")
        if source_toon_id:
            _get_toon_owned(session, source_toon_id, brand_id, user_id)
        source_episode_id = body.get("source_episode_id")
        if source_episode_id:
            _get_episode_owned(session, source_episode_id, brand_id, user_id)
        source_scene_id = body.get("source_scene_id")
        if source_scene_id:
            _get_scene_owned(session, source_scene_id, brand_id, user_id)

        event = CharacterRelationshipEvent(
            relationship_id=relationship.id, brand_id=relationship.brand_id,
            event_type=event_type, description=description,
            affection_delta=deltas.get("affection_delta"), trust_delta=deltas.get("trust_delta"),
            conflict_delta=deltas.get("conflict_delta"),
            source_toon_id=_uuid.UUID(source_toon_id) if source_toon_id else None,
            source_episode_id=_uuid.UUID(source_episode_id) if source_episode_id else None,
            source_scene_id=_uuid.UUID(source_scene_id) if source_scene_id else None,
        )
        session.add(event)
        _apply_relationship_deltas(
            relationship, deltas.get("affection_delta"), deltas.get("trust_delta"), deltas.get("conflict_delta"),
        )
        session.commit()
        session.refresh(event)
        return _serialize_relationship_event(event)
    finally:
        session.close()


@router.get("/relationships/{relationship_id}/events")
def list_relationship_events(relationship_id: str, user_id: str, brand_id: str, limit: int = 50):
    from app.db import SessionLocal
    from app.models.character_relationship_event import CharacterRelationshipEvent
    session = SessionLocal()
    try:
        relationship = _get_relationship_owned(session, relationship_id, brand_id, user_id)
        events = (
            session.query(CharacterRelationshipEvent).filter_by(relationship_id=relationship.id)
            .order_by(CharacterRelationshipEvent.created_at.desc()).limit(limit).all()
        )
        return [_serialize_relationship_event(e) for e in events]
    finally:
        session.close()


@router.delete("/relationship-events/{event_id}")
def delete_relationship_event(event_id: str, user_id: str, brand_id: str):
    """Hard delete — this is a log, not a soft-archivable resource like the
    relationship itself. Does not reverse the event's deltas, see
    CharacterRelationshipEvent's docstring."""
    from app.db import SessionLocal
    from app.models.character_relationship_event import CharacterRelationshipEvent
    session = SessionLocal()
    try:
        event = session.query(CharacterRelationshipEvent).filter_by(id=_uuid.UUID(event_id)).first()
        if not event:
            raise HTTPException(status_code=404, detail="Relationship event not found")
        _get_relationship_owned(session, str(event.relationship_id), brand_id, user_id)
        session.delete(event)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


def resolve_relationships_for_cast(session, brand_id, character_ids: list) -> list:
    """Looks up every stored relationship between any two Characters in
    `character_ids` (deduped, order-independent — a relationship's
    character_a_id/character_b_id order doesn't imply direction). Used by
    culturetoon_script.py's prompt builder when a script casts 2+ characters
    together. Returns serialized relationship dicts — each "directions"
    entry additionally carries from_character_name/to_character_name (not
    part of _serialize_relationship's normal output) so the script prompt
    can name names instead of just UUIDs — plus a "recent_events" key
    (most recent few, newest first) so script generation can reference the
    relationship's trajectory, not just its current-state snapshot. Empty
    list if none or fewer than 2 distinct characters are cast."""
    from app.models.character_relationship import CharacterRelationship
    from app.models.character_relationship_event import CharacterRelationshipEvent
    from app.models.character import Character
    ids = {_uuid.UUID(str(c)) for c in character_ids}
    if len(ids) < 2:
        return []
    relationships = session.query(CharacterRelationship).filter(
        CharacterRelationship.brand_id == _uuid.UUID(str(brand_id)),
        CharacterRelationship.is_active == True,  # noqa: E712
        CharacterRelationship.character_a_id.in_(ids),
        CharacterRelationship.character_b_id.in_(ids),
    ).all()
    if not relationships:
        return []
    name_map = {str(cid): name for cid, name in session.query(Character.id, Character.name).filter(Character.id.in_(ids)).all()}
    serialized = []
    for r in relationships:
        row = _serialize_relationship(session, r)
        for direction in row["directions"]:
            direction["from_character_name"] = name_map.get(direction["from_character_id"], "?")
            direction["to_character_name"] = name_map.get(direction["to_character_id"], "?")
        events = (
            session.query(CharacterRelationshipEvent).filter_by(relationship_id=r.id)
            .order_by(CharacterRelationshipEvent.created_at.desc())
            .limit(_RECENT_EVENTS_FOR_SCRIPT_CONTEXT).all()
        )
        row["recent_events"] = [_serialize_relationship_event(e) for e in events]
        serialized.append(row)
    return serialized


def _gather_script_generation_context(session, brand_id, variants: list, query_text: str = "") -> tuple:
    """Builds the (character_personalities, relationships, memories,
    cultures, performance_context) tuple culturetoon_script.py's generators
    accept, from a cast of already-loaded CharacterVariant ORM objects — one
    place to assemble this so all three suggest_script/
    suggest_script_from_idea/suggest_next_episode_part call sites stay in
    sync rather than each re-deriving it slightly differently. query_text
    grounds the memory semantic search (see
    app/services/culturetoon_memory.py::retrieve_relevant_memories) — the
    persona/cluster context, user idea, or next-part idea, whichever this
    particular script generation is actually about."""
    from app.models.character import Character
    from app.models.culture import Culture
    from app.services.culturetoon_memory import retrieve_relevant_memories
    from app.services.culturetoon_analytics import get_cast_performance_context
    character_ids = list({v.character_id for v in variants})
    if not character_ids:
        return {}, [], [], [], ""
    characters = session.query(Character).filter(Character.id.in_(character_ids)).all()
    character_personalities = {str(c.id): c.personality for c in characters if c.personality}
    relationships = resolve_relationships_for_cast(session, brand_id, character_ids)
    variant_ids = [v.id for v in variants]
    memories = retrieve_relevant_memories(variant_ids, query_text) if query_text.strip() else []
    culture_ids = list({v.culture_id for v in variants if v.culture_id})
    cultures = (
        [_serialize_culture(c) for c in session.query(Culture).filter(Culture.id.in_(culture_ids)).all()]
        if culture_ids else []
    )
    performance_context = get_cast_performance_context(session, brand_id, variant_ids)
    return character_personalities, relationships, memories, cultures, performance_context


def _propagate_portrait_to_untouched_default_variants(session, character):
    """When a character's own portrait changes, any variant that's still
    exactly as create_character auto-created it — no image, no
    description, no culture_tag, i.e. never customized — picks up the
    same portrait. That default variant exists purely so "register for
    video"/Expressions have somewhere to attach for the common "just use
    this character as-is" case; without this, every character needs a
    second, redundant portrait-generation step on the variant before
    Expressions unlock at all (confirmed live: this blocked Expression
    generation with no obvious next action). A variant the user has
    started customizing (any of those three fields set) is left alone —
    this only ever fills in a blank, never overwrites intent."""
    from app.models.character_variant import CharacterVariant
    session.query(CharacterVariant).filter(
        CharacterVariant.character_id == character.id,
        CharacterVariant.image_url.is_(None),
        CharacterVariant.description.is_(None),
        CharacterVariant.culture_tag.is_(None),
    ).update({"image_url": character.base_image_url})


@router.post("/characters/{character_id}/image")
async def upload_character_image(character_id: str, user_id: str = Form(...), brand_id: str = Form(...),
                                  file: UploadFile = File(...)):
    from app.db import SessionLocal
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        character = _get_character_owned(session, character_id, brand_id, user_id)
        data = await file.read()
        path = f"culturetoons/{character.brand_id}/characters/{character.id}.png"
        try:
            url = save_image(data, file.content_type, path)
        except ImageUploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        character.base_image_url = url
        _propagate_portrait_to_untouched_default_variants(session, character)
        session.commit()
        session.refresh(character)
        return _serialize_character(character)
    finally:
        session.close()


@router.post("/characters/{character_id}/reference-image")
async def upload_character_reference_image(character_id: str, user_id: str = Form(...), brand_id: str = Form(...),
                                             file: UploadFile = File(...)):
    """A raw source photo (or hand-drawn reference) to ground AI image
    generation on — kept separate from base_image_url, which holds the
    current generated/curated portrait. See generate_character_image."""
    from app.db import SessionLocal
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        character = _get_character_owned(session, character_id, brand_id, user_id)
        data = await file.read()
        path = f"culturetoons/{character.brand_id}/characters/{character.id}-reference.png"
        try:
            url = save_image(data, file.content_type, path)
        except ImageUploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        character.reference_image_url = url
        session.commit()
        session.refresh(character)
        return _serialize_character(character)
    finally:
        session.close()


@router.post("/characters/{character_id}/generate-image")
def generate_character_image(character_id: str, body: dict):
    """Builds/iterates the character's portrait from a text description
    (optionally grounded on reference_image_url via image-to-image) using
    the same hybrid provider (free Cloudflare Flux, paid Qwen-Image fallback
    — Qwen is used automatically whenever a reference image is supplied,
    since Flux schnell has no image-to-image input) already wired up for
    digest media generation. The raw description is NOT sent as-is — see
    _build_cartoon_prompt, which wraps it with an explicit art-style
    instruction, otherwise a supplied reference photo just gets lightly
    retouched instead of actually re-illustrated. Synchronous: Flux is a
    few seconds, the Qwen fallback is comparable to an LLM call, both well
    within the frontend's 30s AI-generation timeout convention — no need to
    background this the way slower Kling video generation is."""
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        character = _get_character_owned(session, character_id, brand_id, user_id)
        budget_warning = _check_budget_or_raise(session, brand)
        if "description" in body:
            character.description = (body.get("description") or "").strip() or None
        if "art_style" in body:
            if body["art_style"] not in ART_STYLES:
                raise HTTPException(status_code=400, detail=f"Unknown art_style: {body['art_style']}")
            character.art_style = body["art_style"]
        session.commit()
        description = (character.description or "").strip()
        if not description:
            raise HTTPException(status_code=400, detail="A description is required to generate an image")
        prompt = _build_cartoon_prompt(description, character.art_style, bool(character.reference_image_url))

        from app.media.image_hybrid import HybridImageProvider
        try:
            result = HybridImageProvider().generate(prompt, reference_image_url=character.reference_image_url)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Image generation failed: {exc}")

        ext = "jpg" if result.content_type == "image/jpeg" else "png"
        path = f"culturetoons/{character.brand_id}/characters/{character.id}-{_uuid.uuid4().hex[:8]}.{ext}"
        from app.services.culturetoon_media import save_image, ImageUploadError
        try:
            url = save_image(result.asset_bytes, result.content_type, path)
        except ImageUploadError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to store generated image: {exc}")

        from app.services.culturetoon_usage import record_usage
        record_usage(
            session, user_id=user_id, brand_id=brand.id, provider="hybrid_image",
            generation_type="character_image", cost_usd=result.cost_usd,
        )
        if character.base_image_url:
            character.previous_image_urls = (character.previous_image_urls or []) + [character.base_image_url]
        character.base_image_url = url
        _propagate_portrait_to_untouched_default_variants(session, character)
        session.commit()
        session.refresh(character)
        serialized = _serialize_character(character)
        if budget_warning:
            serialized["budget_warning"] = budget_warning
        return serialized
    finally:
        session.close()


# ── character variants ───────────────────────────────────────────────────

@router.post("/variants")
def create_variant(body: dict):
    from app.db import SessionLocal
    user_id, brand_id, character_id = body.get("user_id"), body.get("brand_id"), body.get("character_id")
    if not user_id or not brand_id or not character_id or not body.get("name"):
        raise HTTPException(status_code=400, detail="user_id, brand_id, character_id and name are required")
    session = SessionLocal()
    try:
        from app.models.character_variant import CharacterVariant
        _get_character_owned(session, character_id, brand_id, user_id)
        culture_id = body.get("culture_id")
        if culture_id:
            from app.models.culture import Culture
            if not session.query(Culture).filter_by(id=_uuid.UUID(culture_id)).first():
                raise HTTPException(status_code=404, detail="Culture not found")
        variant = CharacterVariant(
            character_id=_uuid.UUID(character_id),
            name=body["name"],
            culture_tag=body.get("culture_tag"),
            culture_id=_uuid.UUID(culture_id) if culture_id else None,
            description=body.get("description"),
            persona_id=body.get("persona_id"),
        )
        session.add(variant)
        session.commit()
        session.refresh(variant)
        return _serialize_variant(variant)
    finally:
        session.close()


@router.get("/variants")
def list_variants(user_id: str, brand_id: str, character_id: Optional[str] = None, active_only: bool = True):
    from app.db import SessionLocal
    from app.models.character import Character
    from app.models.character_variant import CharacterVariant
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        if character_id:
            _get_character_owned(session, character_id, brand_id, user_id)
            query = session.query(CharacterVariant).filter_by(character_id=_uuid.UUID(character_id))
        else:
            character_ids = [c.id for c in session.query(Character.id).filter_by(brand_id=brand.id).all()]
            query = session.query(CharacterVariant).filter(CharacterVariant.character_id.in_(character_ids))
        if active_only:
            query = query.filter_by(is_active=True)
        variants = query.order_by(CharacterVariant.created_at.asc()).all()
        return [_serialize_variant(v) for v in variants]
    finally:
        session.close()


@router.get("/variants/{variant_id}")
def get_variant(variant_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        return _serialize_variant(variant)
    finally:
        session.close()


@router.put("/variants/{variant_id}")
def update_variant(variant_id: str, body: dict):
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        if "culture_id" in body and body["culture_id"]:
            from app.models.culture import Culture
            if not session.query(Culture).filter_by(id=_uuid.UUID(body["culture_id"])).first():
                raise HTTPException(status_code=404, detail="Culture not found")
        for field in ("name", "culture_tag", "culture_id", "description", "persona_id", "is_active",
                      "voice_provider", "elevenlabs_voice_id"):
            if field in body:
                setattr(variant, field, _uuid.UUID(body[field]) if field == "culture_id" and body[field] else body[field])
        session.commit()
        session.refresh(variant)
        return _serialize_variant(variant)
    finally:
        session.close()


@router.delete("/variants/{variant_id}")
def delete_variant(variant_id: str, user_id: str, brand_id: str):
    """Soft-delete, same pattern as delete_background/delete_character:
    flips is_active off rather than removing the row, so scripts/toons that
    already reference this variant keep working. list_variants already
    filters to active_only=True by default, so this is enough to make the
    variant disappear from the roster."""
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        variant.is_active = False
        session.commit()
        return {"status": "deactivated"}
    finally:
        session.close()


@router.post("/variants/{variant_id}/image")
async def upload_variant_image(variant_id: str, user_id: str = Form(...), brand_id: str = Form(...),
                                file: UploadFile = File(...)):
    from app.db import SessionLocal
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        from app.models.character import Character
        character = session.query(Character).filter_by(id=variant.character_id).first()
        data = await file.read()
        path = f"culturetoons/{character.brand_id}/variants/{variant.id}.png"
        try:
            url = save_image(data, file.content_type, path)
        except ImageUploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        variant.image_url = url
        session.commit()
        session.refresh(variant)
        return _serialize_variant(variant)
    finally:
        session.close()


@router.post("/variants/{variant_id}/reference-image")
async def upload_variant_reference_image(variant_id: str, user_id: str = Form(...), brand_id: str = Form(...),
                                          file: UploadFile = File(...)):
    """A variant-specific raw source photo, if the user has one (e.g. a real
    photo for the "Wife" variant) — kept separate from image_url, which
    holds the current generated/curated portrait. See generate_variant_image,
    which falls back to the parent Character's own portrait when this is
    absent, so a variant with no photo of its own still resembles the rest
    of the roster."""
    from app.db import SessionLocal
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        from app.models.character import Character
        character = session.query(Character).filter_by(id=variant.character_id).first()
        data = await file.read()
        path = f"culturetoons/{character.brand_id}/variants/{variant.id}-reference.png"
        try:
            url = save_image(data, file.content_type, path)
        except ImageUploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        variant.reference_image_url = url
        session.commit()
        session.refresh(variant)
        return _serialize_variant(variant)
    finally:
        session.close()


@router.post("/variants/{variant_id}/generate-image")
def generate_variant_image(variant_id: str, body: dict):
    """Builds/iterates this variant's portrait — same idea as
    generate_character_image, but scoped to one cultural/relational variant
    of the base character (e.g. "Wife of Kumar", "Chinese version").

    Grounding image priority: the variant's own reference_image_url if
    present (preserve_identity=True — that photo IS this variant); else,
    if the variant has an explicit culture_tag (an intentional
    ethnicity/cultural-look change, e.g. "Chinese version" of an Indian
    character), NO reference image at all — confirmed LIVE that grounding
    an ethnicity change on the base character's own photo reliably fails:
    Qwen-Image's image-to-image keeps the reference face/ethnicity
    regardless of "recast this as a different actor" prompt instructions,
    no matter how explicit. Dropping the reference image and generating
    from a concrete text description only (_expand_variant_visual_description
    below) is what actually produces the requested ethnicity. Only when
    there's no photo of its own AND no culture_tag (e.g. "grumpier version
    of the same guy", same ethnicity intended) does this still ground on
    the base character's photo for family resemblance."""
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        budget_warning = _check_budget_or_raise(session, brand)
        from app.models.character import Character
        character = session.query(Character).filter_by(id=variant.character_id).first()
        if "description" in body:
            variant.description = (body.get("description") or "").strip() or None
        if "culture_tag" in body:
            variant.culture_tag = (body.get("culture_tag") or "").strip() or None
        session.commit()
        raw_description = (variant.description or "").strip()
        if not raw_description:
            raise HTTPException(status_code=400, detail="A description is required to generate an image")

        has_own_reference = bool(variant.reference_image_url)
        extra = f"This is a variant of the base character '{character.name}', called '{variant.name}'."
        expansion_degraded = False

        if has_own_reference:
            reference_image_url = variant.reference_image_url
            description = raw_description
            if variant.culture_tag:
                extra += f" Ethnicity / cultural appearance: {variant.culture_tag}."
        elif character.base_image_url and variant.culture_tag:
            # No photo of its own, but an explicit ethnicity/cultural-look
            # signal — confirmed LIVE (real Qwen-Image calls, side by side)
            # that grounding this case on the base character's photo
            # reliably fails to actually change ethnicity: Qwen-Image's
            # image-to-image keeps the reference face/features regardless
            # of "recast this as a different actor" prompt instructions.
            # Dropping the reference image and generating from text only is
            # what actually produces the requested ethnicity — verified by
            # generating both versions of the exact same "Chinese variant of
            # an Indian character" case and comparing the output images.
            reference_image_url = None
            description, expansion_degraded = _expand_variant_visual_description(character, variant, raw_description)
            extra += f" Ethnicity / cultural appearance: {variant.culture_tag}."
        elif character.base_image_url:
            # No explicit ethnicity signal — assume family resemblance to
            # the base character is actually wanted (e.g. "grumpier version
            # of the same guy"), keep grounding on their photo.
            reference_image_url = character.base_image_url
            description, expansion_degraded = _expand_variant_visual_description(character, variant, raw_description)
        else:
            reference_image_url = None
            description = raw_description
            if variant.culture_tag:
                extra += f" Ethnicity / cultural appearance: {variant.culture_tag}."

        prompt = _build_cartoon_prompt(
            description, character.art_style, bool(reference_image_url),
            preserve_identity=has_own_reference, extra=extra,
        )

        from app.media.image_hybrid import HybridImageProvider
        try:
            result = HybridImageProvider().generate(prompt, reference_image_url=reference_image_url)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Image generation failed: {exc}")

        ext = "jpg" if result.content_type == "image/jpeg" else "png"
        path = f"culturetoons/{character.brand_id}/variants/{variant.id}-{_uuid.uuid4().hex[:8]}.{ext}"
        from app.services.culturetoon_media import save_image, ImageUploadError
        try:
            url = save_image(result.asset_bytes, result.content_type, path)
        except ImageUploadError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to store generated image: {exc}")

        from app.services.culturetoon_usage import record_usage
        record_usage(
            session, user_id=user_id, brand_id=brand.id, provider="hybrid_image",
            generation_type="variant_image", cost_usd=result.cost_usd,
        )
        if variant.image_url:
            variant.previous_image_urls = (variant.previous_image_urls or []) + [variant.image_url]
        variant.image_url = url
        session.commit()
        session.refresh(variant)
        serialized = _serialize_variant(variant)
        if expansion_degraded:
            # Not a hard failure (generation still produced an image), but
            # confirmed live this silent path produces a materially worse
            # result — no ethnicity/attire anchor at all — so the caller
            # gets a transient, non-persisted warning instead of a
            # generation that looks identical to a successful one.
            serialized["generation_warning"] = (
                "The AI description-expansion step failed, so this portrait was generated from your "
                "raw description alone, with no explicit ethnicity/attire detail. Result quality may be "
                "lower than usual — consider regenerating."
            )
        if budget_warning:
            serialized["budget_warning"] = budget_warning
        return serialized
    finally:
        session.close()


@router.post("/variants/{variant_id}/register-element")
def register_variant_element(variant_id: str, body: dict, background_tasks: BackgroundTasks):
    """Backgrounded — element (+ optional voice) creation is a multi-step
    async Kling operation, not guaranteed sub-second. Sets element_status
    to 'pending' synchronously so the UI sees the state flip immediately."""
    from app.db import SessionLocal
    from app.services.culturetoon_element import register_character_variant

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        if not variant.image_url:
            raise HTTPException(status_code=400, detail="Variant has no image to register — upload one first")
        budget_warning = _check_budget_or_raise(session, brand)
        variant.element_status = "pending"
        session.commit()
    finally:
        session.close()

    background_tasks.add_task(
        register_character_variant,
        user_id=user_id, brand_id=brand_id, variant_id=variant_id,
        refer_image_urls=body.get("refer_image_urls"),
        voice_sample_url=body.get("voice_sample_url"),
        preset_voice_id=body.get("preset_voice_id"),
        voice_provider=body.get("voice_provider", "kling"),
        elevenlabs_voice_id=body.get("elevenlabs_voice_id"),
    )
    response = {"status": "registration_started"}
    if budget_warning:
        response["budget_warning"] = budget_warning
    return response


@router.post("/variants/{variant_id}/lora-training-images")
async def upload_lora_training_images(variant_id: str, user_id: str = Form(...), brand_id: str = Form(...),
                                       files: list[UploadFile] = File(...)):
    """Uploads one or more reference images for this variant's self-hosted
    (RunPod+ComfyUI+LTX-2) LoRA training set — see
    app/services/culturetoon_lora.py. Accumulates across multiple calls
    (doesn't replace the existing set) so a user can build up toward
    MIN_LORA_TRAINING_IMAGES incrementally."""
    from app.db import SessionLocal
    from app.services.culturetoon_media import save_image, ImageUploadError
    from app.services.culturetoon_lora import add_training_images

    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        uploaded_urls = []
        for i, file in enumerate(files):
            data = await file.read()
            existing_count = len(variant.lora_training_images or []) + i
            path = f"culturetoons/{variant.character_id}/{variant.id}/lora-training/{existing_count}.png"
            try:
                uploaded_urls.append(save_image(data, file.content_type, path))
            except ImageUploadError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        add_training_images(variant, uploaded_urls)
        session.commit()
        session.refresh(variant)
        return _serialize_variant(variant)
    finally:
        session.close()


@router.post("/variants/{variant_id}/train-lora")
def train_variant_lora(variant_id: str, body: dict, background_tasks: BackgroundTasks):
    """Backgrounded — a full ltx-trainer run over SSH can take up to an
    hour (see culturetoon_lora.py's _TRAINING_TIMEOUT_SECONDS), far past any
    HTTP gateway timeout. Sets lora_status to 'training' synchronously so
    the UI sees the state flip immediately, same pattern as
    register_variant_element's element_status='pending'."""
    from app.db import SessionLocal
    from app.services.culturetoon_lora import MIN_LORA_TRAINING_IMAGES, run_lora_training, curate_training_images

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        # Culturix decides the training set (curate_training_images) —
        # this variant's own Expression images by default, not just
        # whatever's been manually uploaded — so this count reflects what
        # will actually be trained on, not a raw upload tally.
        image_count = len(curate_training_images(session, variant))
        if image_count < MIN_LORA_TRAINING_IMAGES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Need at least {MIN_LORA_TRAINING_IMAGES} training images, have {image_count}. "
                    "Generate this variant's remaining Expressions to reach the minimum automatically, "
                    "or upload supplemental reference images."
                ),
            )
        variant.lora_status = "training"
        variant.lora_error = None
        session.commit()
    finally:
        session.close()

    background_tasks.add_task(run_lora_training, variant_id=variant_id)
    return {"status": "training_started"}


@router.post("/variants/{variant_id}/lora-preview")
def generate_lora_preview(variant_id: str, body: dict, background_tasks: BackgroundTasks):
    """Backgrounded, same reasoning as /train-lora — a Serverless generation
    call (cold start + sampling) can take minutes. Sets lora_preview_status
    to 'generating' synchronously so the UI sees the state flip immediately.
    See CharacterVariant.lora_preview_url's docstring for why this exists:
    there's no automated quality signal for a trained LoRA otherwise."""
    from app.db import SessionLocal
    from app.services.culturetoon_lora import run_lora_preview

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        if variant.lora_status != "ready" or not variant.lora_path:
            raise HTTPException(status_code=400, detail="This variant has no ready trained LoRA to preview")
        variant.lora_preview_status = "generating"
        variant.lora_preview_error = None
        session.commit()
    finally:
        session.close()

    background_tasks.add_task(run_lora_preview, variant_id=variant_id, user_id=user_id)
    return {"status": "preview_started"}


# ── expressions ───────────────────────────────────────────────────────────

@router.get("/variants/{variant_id}/expressions")
def list_expressions(variant_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    from app.models.expression import Expression
    session = SessionLocal()
    try:
        _get_variant_owned(session, variant_id, brand_id, user_id)
        expressions = (
            session.query(Expression)
            .filter_by(character_variant_id=_uuid.UUID(variant_id))
            .order_by(Expression.name.asc())
            .all()
        )
        return [_serialize_expression(e) for e in expressions]
    finally:
        session.close()


@router.post("/variants/{variant_id}/expressions/{name}/image")
async def upload_expression_image(variant_id: str, name: str, user_id: str = Form(...), brand_id: str = Form(...),
                                   file: UploadFile = File(...)):
    if name not in EXPRESSION_NAMES:
        raise HTTPException(status_code=400, detail=f"name must be one of {EXPRESSION_NAMES}")
    from app.db import SessionLocal
    from app.models.expression import Expression
    from app.models.character import Character
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        character = session.query(Character).filter_by(id=variant.character_id).first()
        data = await file.read()
        path = f"culturetoons/{character.brand_id}/variants/{variant.id}/expressions/{name}.png"
        try:
            url = save_image(data, file.content_type, path)
        except ImageUploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        expression = (
            session.query(Expression)
            .filter_by(character_variant_id=_uuid.UUID(variant_id), name=name)
            .first()
        )
        if expression:
            expression.image_url = url
        else:
            expression = Expression(character_variant_id=_uuid.UUID(variant_id), name=name, image_url=url)
            session.add(expression)
        session.commit()
        session.refresh(expression)
        return _serialize_expression(expression)
    finally:
        session.close()


def _generate_one_expression_image(session, variant, character, name: str):
    """Core of generate_expression_image, extracted so
    generate_all_expression_images can call it per-name in a loop without
    duplicating the prompt/provider/storage logic. Raises on failure (same
    exceptions as before extraction) — callers decide whether that should
    abort the whole request (single-expression endpoint) or just be
    recorded as one failure among many (bulk endpoint)."""
    from app.models.expression import Expression

    hint = EXPRESSION_PROMPT_HINTS.get(name, f"a {name.lower()} facial expression")
    style = ART_STYLES.get(character.art_style if character else DEFAULT_ART_STYLE, ART_STYLES[DEFAULT_ART_STYLE])
    # Deliberately NOT _build_cartoon_prompt's preserve_identity=True
    # branch — that one is written for regenerating a fresh portrait
    # from a reference photo (explicitly wants "a different framing and
    # setting... redraw everything else, including clothing"), which is
    # the opposite of what an expression variant needs: the SAME pose,
    # clothing, and framing as the base portrait, with only the face
    # changed.
    prompt = (
        f"Same character, same {style['prompt']}, same pose, same clothing, same framing and "
        f"background as the reference image — change ONLY the facial expression to {hint}. "
        "Everything else about the character must stay identical to the reference."
    )

    from app.media.image_hybrid import HybridImageProvider
    try:
        result = HybridImageProvider().generate(prompt, reference_image_url=variant.image_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Image generation failed: {exc}")

    path = f"culturetoons/{variant.character_id}/variants/{variant.id}/expressions/{name}-{_uuid.uuid4().hex[:8]}.png"
    from app.services.culturetoon_media import save_image, ImageUploadError
    try:
        url = save_image(result.asset_bytes, result.content_type, path)
    except ImageUploadError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to store generated image: {exc}")

    expression = (
        session.query(Expression)
        .filter_by(character_variant_id=variant.id, name=name)
        .first()
    )
    if expression:
        expression.image_url = url
    else:
        expression = Expression(character_variant_id=variant.id, name=name, image_url=url)
        session.add(expression)
    session.commit()
    session.refresh(expression)
    return expression


@router.post("/variants/{variant_id}/expressions/{name}/generate-image")
def generate_expression_image(variant_id: str, name: str, body: dict):
    """AI-generates one expression image, grounded on this variant's own
    portrait — added because the upload-only flow above put the user in the
    position of having to source 10 separate photos of an AI-generated
    character themselves (confirmed live: genuinely confusing — "the avatar
    was created by the AI not me"). Reuses the exact same
    HybridImageProvider/_build_cartoon_prompt pipeline as the portrait
    itself, with preserve_identity=True (this IS the same character, just a
    different expression — not a recast) grounded on variant.image_url."""
    if name not in EXPRESSION_NAMES:
        raise HTTPException(status_code=400, detail=f"name must be one of {EXPRESSION_NAMES}")
    from app.db import SessionLocal
    from app.models.character import Character

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        character = session.query(Character).filter_by(id=variant.character_id).first()
        if not variant.image_url:
            raise HTTPException(status_code=400, detail="Build this variant's own portrait first — expressions are generated from it")

        expression = _generate_one_expression_image(session, variant, character, name)
        return _serialize_expression(expression)
    finally:
        session.close()


def run_generate_all_expressions(variant_id: str) -> None:
    """Background-task entry point (POST /variants/{id}/expressions/
    generate-all) — owns its own session lifecycle since it runs after the
    request's own session has already closed, same shape as
    run_lora_training. Fills every EXPRESSION_NAMES slot that doesn't
    already have an image, skipping ones that do (idempotent/safe to
    re-run — doesn't burn cost regenerating choices the user already
    kept). Continues past a single name's failure instead of aborting the
    whole batch — partial progress (e.g. 8 of 10 succeeded) is still
    useful, and the frontend's existing per-expression Regenerate button
    already covers retrying whichever ones end up in
    expressions_generate_errors. Confirmed live 2026-08-20: running this
    synchronously inside one HTTP request got killed mid-batch by Vercel's
    own serverless function execution limit — ten sequential paid
    image-generation calls run well past it regardless of what the
    client-side fetch allows, so this has to be backgrounded and polled
    like element/LoRA registration, not just given a longer timeout."""
    import uuid as _uuid
    from app.db import SessionLocal
    from app.models.character_variant import CharacterVariant
    from app.models.character import Character
    from app.models.expression import Expression

    session = SessionLocal()
    try:
        variant = session.query(CharacterVariant).filter_by(id=_uuid.UUID(str(variant_id))).first()
        if not variant:
            return
        character = session.query(Character).filter_by(id=variant.character_id).first()

        existing = {
            e.name: e for e in session.query(Expression).filter_by(character_variant_id=variant.id).all()
        }
        errors: dict = {}
        for name in EXPRESSION_NAMES:
            if name in existing and existing[name].image_url:
                continue
            try:
                existing[name] = _generate_one_expression_image(session, variant, character, name)
            except HTTPException as exc:
                errors[name] = exc.detail if isinstance(exc.detail, str) else str(exc.detail)

        variant.expressions_generating = False
        variant.expressions_generate_errors = errors
        session.commit()
    finally:
        session.close()


@router.post("/variants/{variant_id}/expressions/generate-all")
def generate_all_expression_images(variant_id: str, body: dict, background_tasks: BackgroundTasks):
    """One-click version of generate_expression_image — fills in every
    EXPRESSION_NAMES slot that doesn't already have an image, so a user
    doesn't have to click "Generate" ten separate times after building a
    character. Backgrounded (see run_generate_all_expressions) — sets
    expressions_generating=True synchronously so the UI sees the state
    flip immediately, same pattern as register_variant_element/
    train_variant_lora. The frontend polls the variant (existing
    element_status/lora_status poll effect, extended to also watch this
    flag) rather than this endpoint returning the results directly."""
    if not EXPRESSION_NAMES:
        return {"status": "nothing_to_generate"}
    from app.db import SessionLocal

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        if not variant.image_url:
            raise HTTPException(status_code=400, detail="Build this variant's own portrait first — expressions are generated from it")
        variant.expressions_generating = True
        variant.expressions_generate_errors = None
        session.commit()
    finally:
        session.close()

    background_tasks.add_task(run_generate_all_expressions, variant_id=variant_id)
    return {"status": "generation_started"}


@router.delete("/expressions/{expression_id}")
def delete_expression(expression_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    from app.models.expression import Expression
    session = SessionLocal()
    try:
        expression = session.query(Expression).filter_by(id=_uuid.UUID(expression_id)).first()
        if not expression:
            raise HTTPException(status_code=404, detail="Expression not found")
        _get_variant_owned(session, str(expression.character_variant_id), brand_id, user_id)
        session.delete(expression)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


# ── cultures ─────────────────────────────────────────────────────────────
# Global shared reference library, not brand-scoped — see Culture's
# docstring (app/models/culture.py).

def _serialize_culture(c) -> dict:
    return {
        "id": str(c.id), "name": c.name, "country": c.country, "region": c.region,
        "language": c.language, "cultural_patterns": c.cultural_patterns,
        "humor_sensitivity": c.humor_sensitivity,
        "common_misunderstandings": c.common_misunderstandings or [],
        "stereotypes_to_avoid": c.stereotypes_to_avoid or [],
        "positive_traits": c.positive_traits or [],
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("/cultures")
def list_cultures(active_only: bool = True):
    from app.db import SessionLocal
    from app.models.culture import Culture
    session = SessionLocal()
    try:
        query = session.query(Culture)
        if active_only:
            query = query.filter_by(is_active=True)
        cultures = query.order_by(Culture.name.asc()).all()
        return [_serialize_culture(c) for c in cultures]
    finally:
        session.close()


@router.post("/cultures")
def create_culture(body: dict):
    """Any authenticated user can add to the shared library — it's meant to
    grow as an open reference, not gated behind admin approval. user_id is
    still required (basic auth, matching every other route's convention)
    even though the row itself isn't user-owned."""
    from app.db import SessionLocal
    from app.models.culture import Culture

    if not body.get("user_id"):
        raise HTTPException(status_code=400, detail="user_id is required")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    session = SessionLocal()
    try:
        if session.query(Culture).filter_by(name=name).first():
            raise HTTPException(status_code=409, detail=f"Culture '{name}' already exists")
        culture = Culture(
            name=name, country=body.get("country"), region=body.get("region"), language=body.get("language"),
            cultural_patterns=body.get("cultural_patterns"), humor_sensitivity=body.get("humor_sensitivity"),
            common_misunderstandings=body.get("common_misunderstandings"),
            stereotypes_to_avoid=body.get("stereotypes_to_avoid"),
            positive_traits=body.get("positive_traits"),
        )
        session.add(culture)
        session.commit()
        session.refresh(culture)
        return _serialize_culture(culture)
    finally:
        session.close()


# ── memories ─────────────────────────────────────────────────────────────
# Variant-level, not character-level — see CharacterMemory's docstring.

_MEMORY_TYPES = [
    "backstory", "recurring_fact", "relationship_event",
    "previous_joke", "preference", "running_gag", "episode_event",
]


def _serialize_memory(m) -> dict:
    return {
        "id": str(m.id), "character_variant_id": str(m.character_variant_id), "brand_id": str(m.brand_id),
        "memory_type": m.memory_type, "content": m.content, "importance": m.importance,
        "source_toon_id": str(m.source_toon_id) if m.source_toon_id else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.post("/variants/{variant_id}/memories")
def create_memory(variant_id: str, body: dict):
    from app.db import SessionLocal
    from app.models.character_memory import CharacterMemory
    from app.services.culturetoon_memory import index_memory

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    memory_type = body.get("memory_type")
    content = (body.get("content") or "").strip()
    if not user_id or not brand_id or not content:
        raise HTTPException(status_code=400, detail="user_id, brand_id and content are required")
    if memory_type not in _MEMORY_TYPES:
        raise HTTPException(status_code=400, detail=f"memory_type must be one of {_MEMORY_TYPES}")
    importance = body.get("importance")
    if importance is not None and not (0 <= int(importance) <= 10):
        raise HTTPException(status_code=400, detail="importance must be between 0 and 10")

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        source_toon_id = body.get("source_toon_id")
        if source_toon_id:
            _get_toon_owned(session, source_toon_id, brand_id, user_id)
        memory = CharacterMemory(
            character_variant_id=variant.id, brand_id=brand.id,
            memory_type=memory_type, content=content, importance=importance,
            source_toon_id=_uuid.UUID(source_toon_id) if source_toon_id else None,
        )
        session.add(memory)
        session.commit()
        session.refresh(memory)
        index_memory(memory)  # best-effort, see culturetoon_memory.py
        return _serialize_memory(memory)
    finally:
        session.close()


@router.get("/variants/{variant_id}/memories")
def list_memories(variant_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    from app.models.character_memory import CharacterMemory
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        memories = (
            session.query(CharacterMemory).filter_by(character_variant_id=variant.id)
            .order_by(CharacterMemory.created_at.desc()).all()
        )
        return [_serialize_memory(m) for m in memories]
    finally:
        session.close()


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    from app.models.character_memory import CharacterMemory
    from app.services.culturetoon_memory import delete_memory_index

    session = SessionLocal()
    try:
        memory = session.query(CharacterMemory).filter_by(id=_uuid.UUID(memory_id)).first()
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        _get_variant_owned(session, str(memory.character_variant_id), brand_id, user_id)
        session.delete(memory)
        session.commit()
        delete_memory_index(memory_id)
        return {"status": "deleted"}
    finally:
        session.close()


# ── backgrounds ───────────────────────────────────────────────────────────

@router.post("/backgrounds")
def create_background(body: dict):
    from app.db import SessionLocal
    from app.models.toon_background import ToonBackground
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id or not body.get("name"):
        raise HTTPException(status_code=400, detail="user_id, brand_id and name are required")
    visual_style = body.get("visual_style")
    if visual_style is not None and visual_style not in ART_STYLES:
        raise HTTPException(status_code=400, detail=f"visual_style must be one of {list(ART_STYLES)}")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        background = ToonBackground(
            brand_id=brand.id, name=body["name"], tags=body.get("tags"),
            description=body.get("description"),
            country=body.get("country"), visual_style=visual_style,
        )
        session.add(background)
        session.commit()
        session.refresh(background)
        return _serialize_background(background)
    finally:
        session.close()


@router.get("/backgrounds")
def list_backgrounds(user_id: str, brand_id: str, active_only: bool = True):
    from app.db import SessionLocal
    from app.models.toon_background import ToonBackground
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        query = session.query(ToonBackground).filter_by(brand_id=brand.id)
        if active_only:
            query = query.filter_by(is_active=True)
        backgrounds = query.order_by(ToonBackground.created_at.asc()).all()
        return [_serialize_background(bg) for bg in backgrounds]
    finally:
        session.close()


@router.put("/backgrounds/{background_id}")
def update_background(background_id: str, body: dict):
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    if body.get("visual_style") is not None and body["visual_style"] not in ART_STYLES:
        raise HTTPException(status_code=400, detail=f"visual_style must be one of {list(ART_STYLES)}")
    session = SessionLocal()
    try:
        background = _get_background_owned(session, background_id, brand_id, user_id)
        for field in ("name", "tags", "description", "country", "visual_style", "is_active"):
            if field in body:
                setattr(background, field, body[field])
        session.commit()
        session.refresh(background)
        return _serialize_background(background)
    finally:
        session.close()


@router.post("/backgrounds/{background_id}/reference-images")
async def upload_background_reference_image(background_id: str, user_id: str = Form(...), brand_id: str = Form(...),
                                              file: UploadFile = File(...)):
    """Adds one more canonical angle/room for this location, alongside
    (not replacing) its primary image_url — see ToonBackground's docstring."""
    from app.db import SessionLocal
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        background = _get_background_owned(session, background_id, brand_id, user_id)
        data = await file.read()
        existing_count = len(background.reference_image_urls or [])
        path = f"culturetoons/{background.brand_id}/backgrounds/{background.id}-ref-{existing_count + 1}.png"
        try:
            url = save_image(data, file.content_type, path)
        except ImageUploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        background.reference_image_urls = (background.reference_image_urls or []) + [url]
        session.commit()
        session.refresh(background)
        return _serialize_background(background)
    finally:
        session.close()


@router.delete("/backgrounds/{background_id}/reference-images")
def delete_background_reference_image(background_id: str, user_id: str, brand_id: str, image_url: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        background = _get_background_owned(session, background_id, brand_id, user_id)
        background.reference_image_urls = [u for u in (background.reference_image_urls or []) if u != image_url]
        session.commit()
        session.refresh(background)
        return _serialize_background(background)
    finally:
        session.close()


@router.post("/backgrounds/{background_id}/image")
async def upload_background_image(background_id: str, user_id: str = Form(...), brand_id: str = Form(...),
                                   file: UploadFile = File(...)):
    from app.db import SessionLocal
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        background = _get_background_owned(session, background_id, brand_id, user_id)
        data = await file.read()
        path = f"culturetoons/{background.brand_id}/backgrounds/{background.id}.png"
        try:
            url = save_image(data, file.content_type, path)
        except ImageUploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        background.image_url = url
        session.commit()
        session.refresh(background)
        return _serialize_background(background)
    finally:
        session.close()


@router.delete("/backgrounds/{background_id}")
def delete_background(background_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        background = _get_background_owned(session, background_id, brand_id, user_id)
        background.is_active = False
        session.commit()
        return {"status": "deactivated"}
    finally:
        session.close()


# ── scripts ───────────────────────────────────────────────────────────────

@router.post("/scripts")
def create_script(body: dict):
    from app.db import SessionLocal
    from app.models.toon_script import ToonScript
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        character_variant_id = body.get("character_variant_id")
        if character_variant_id:
            _get_variant_owned(session, character_variant_id, brand_id, user_id)
        script = ToonScript(
            brand_id=brand.id,
            character_variant_id=_uuid.UUID(character_variant_id) if character_variant_id else None,
            hook_line=body.get("hook_line"),
            dialogue=body.get("dialogue"),
            scene_direction=body.get("scene_direction"),
            generation_source="manual",
            status="draft",
        )
        session.add(script)
        session.commit()
        session.refresh(script)
        return _serialize_script(script)
    finally:
        session.close()


def _validate_script_generation_params(body: dict) -> tuple:
    """Shared by suggest_script and suggest_script_from_idea. Bounds-checks
    num_shots/target_duration_seconds against the general, provider-agnostic
    script-creation ceiling (MIN_SHOTS/MAX_SHOTS/MIN_TOTAL_SECONDS/
    MAX_TOTAL_SECONDS in culturetoon_script.py — sized for self-hosted,
    which has no real per-call duration limit) before spending an LLM call.
    Kling Omni's own, much smaller, real ceiling (KLING_MAX_SHOTS/
    KLING_MAX_TOTAL_SECONDS) is enforced separately, at generate-time in
    generate_toon_video below, since a script isn't tied to a provider
    until then."""
    from app.services.culturetoon_script import MIN_SHOTS, MAX_SHOTS, MIN_TOTAL_SECONDS, MAX_TOTAL_SECONDS
    num_shots = body.get("num_shots", 4)
    target_duration_seconds = body.get("target_duration_seconds", 12)
    try:
        num_shots = int(num_shots)
        target_duration_seconds = int(target_duration_seconds)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="num_shots and target_duration_seconds must be integers")
    if not (MIN_SHOTS <= num_shots <= MAX_SHOTS):
        raise HTTPException(status_code=400, detail=f"num_shots must be between {MIN_SHOTS} and {MAX_SHOTS}")
    if not (MIN_TOTAL_SECONDS <= target_duration_seconds <= MAX_TOTAL_SECONDS):
        raise HTTPException(
            status_code=400,
            detail=f"target_duration_seconds must be between {MIN_TOTAL_SECONDS} and {MAX_TOTAL_SECONDS}",
        )
    return num_shots, target_duration_seconds


def _extract_cast_ids(body: dict) -> list:
    """Cheap, no-DB extraction of the requested cast id list from either
    character_variant_ids (the multi-character path) or the older single
    character_variant_id, so existing callers keep working. Split out from
    _resolve_cast so callers can fail fast on a missing cast before opening
    a session or doing any other lookup — an empty/missing cast used to
    silently produce a script about no one in particular, leaving the LLM
    free to invent a fictional character instead (confirmed live: a
    "Marvel purist" that isn't a real roster character)."""
    raw_ids = body.get("character_variant_ids")
    if not raw_ids:
        single = body.get("character_variant_id")
        raw_ids = [single] if single else []
    return [v for v in raw_ids if v]


def _resolve_cast(session, body: dict, brand_id: str, user_id: str) -> list:
    """The DB-touching half of cast resolution: caps at
    MAX_CHARACTERS_PER_VIDEO (the same limit generate_video_for_toon
    enforces, so a script that can never actually generate a video isn't
    created in the first place) and resolves+validates ownership of each
    id. Callers should already have checked _extract_cast_ids(body) is
    non-empty before opening a session."""
    from app.services.culturetoon_video import MAX_CHARACTERS_PER_VIDEO

    raw_ids = _extract_cast_ids(body)
    if len(raw_ids) > MAX_CHARACTERS_PER_VIDEO:
        raise HTTPException(
            status_code=400,
            detail=f"At most {MAX_CHARACTERS_PER_VIDEO} characters are supported per script",
        )
    return [_get_variant_owned(session, vid, brand_id, user_id) for vid in raw_ids]


@router.post("/scripts/suggest")
def suggest_script(body: dict):
    """Synchronous — a single LLM call, matching shopify_generate_product_idea's
    pattern (the caller needs the result immediately to render it)."""
    from app.db import SessionLocal
    from app.models.toon_script import ToonScript
    from app.services.culturetoon_script import generate_toon_script, judge_script_comedy, ToonScriptGenerationError, TONE_OPTIONS as _TONES

    user_id = body.get("user_id")
    brand_id = body.get("brand_id")
    source_type = body.get("source_type")
    source_id = body.get("source_id")
    tone = body.get("tone", "funny")

    if not user_id or not brand_id or source_type not in ("persona", "cluster") or source_id is None:
        raise HTTPException(status_code=400, detail="user_id, brand_id, source_type ('persona'|'cluster') and source_id are required")
    if not _extract_cast_ids(body):
        raise HTTPException(
            status_code=400,
            detail="character_variant_ids (or character_variant_id) is required — pick at least one real character",
        )
    if tone not in _TONES:
        raise HTTPException(status_code=400, detail=f"tone must be one of {_TONES}")
    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="source_id must be an integer")
    num_shots, target_duration_seconds = _validate_script_generation_params(body)

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        # Resolve cast (cap + ownership check) before the trend-source lookup
        # so a too-large or unowned cast fails with its own 400/404 rather
        # than being masked by an unrelated 404 when source_id also happens
        # not to exist (caught by test_suggest_exceeds_max_characters_400s).
        variants = _resolve_cast(session, body, brand_id, user_id)
        source = _fetch_trend_source(session, source_type, source_id)
        if not source:
            raise HTTPException(status_code=404, detail=f"{source_type} {source_id} not found")
        source_query_text = getattr(source, "description", None) or getattr(source, "summary", None) or getattr(source, "theme", None) or ""
        character_personalities, relationships, memories, cultures, performance_context = _gather_script_generation_context(
            session, brand_id, variants, source_query_text
        )

        try:
            idea = generate_toon_script(
                source, variants, tone=tone,
                num_shots=num_shots,
                target_duration_seconds=target_duration_seconds,
                character_personalities=character_personalities,
                relationships=relationships,
                memories=memories,
                cultures=cultures,
                performance_context=performance_context,
            )
        except ToonScriptGenerationError as exc:
            raise HTTPException(status_code=502, detail=f"Script generation failed: {exc}")

        script = ToonScript(
            brand_id=brand.id,
            character_variant_id=variants[0].id,
            character_variant_ids=[str(v.id) for v in variants],
            source_type=source_type,
            source_id=source_id,
            hook_line=idea.get("hook_line"),
            tone=idea.get("tone"),
            shots=idea.get("shots"),
            total_duration_seconds=idea.get("total_duration_seconds"),
            comedy_judgment=judge_script_comedy(idea),
            generation_source="ai",
            status="draft",
        )
        session.add(script)
        session.commit()
        session.refresh(script)
        return _serialize_script(script)
    finally:
        session.close()


@router.post("/scripts/suggest-from-idea")
def suggest_script_from_idea(body: dict):
    """Same shape as suggest_script, but grounded in the user's own
    free-text scenario idea instead of a live Persona/Cluster — for anyone
    who already knows what they want the character to react to and doesn't
    want to browse/wait for trends. Synchronous, same reasoning as
    suggest_script: a single LLM call, the caller needs the result to
    render it immediately."""
    from app.db import SessionLocal
    from app.models.toon_script import ToonScript
    from app.services.culturetoon_script import (
        generate_toon_script_from_idea, judge_script_comedy, ToonScriptGenerationError, TONE_OPTIONS as _TONES,
    )

    user_id = body.get("user_id")
    brand_id = body.get("brand_id")
    idea = (body.get("idea") or "").strip()
    tone = body.get("tone", "funny")

    if not user_id or not brand_id or not idea:
        raise HTTPException(status_code=400, detail="user_id, brand_id and idea are required")
    if not _extract_cast_ids(body):
        raise HTTPException(
            status_code=400,
            detail="character_variant_ids (or character_variant_id) is required — pick at least one real character",
        )
    if tone not in _TONES:
        raise HTTPException(status_code=400, detail=f"tone must be one of {_TONES}")
    num_shots, target_duration_seconds = _validate_script_generation_params(body)

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        variants = _resolve_cast(session, body, brand_id, user_id)
        character_personalities, relationships, memories, cultures, performance_context = _gather_script_generation_context(
            session, brand_id, variants, idea
        )

        try:
            result = generate_toon_script_from_idea(
                idea, variants, tone=tone,
                num_shots=num_shots,
                target_duration_seconds=target_duration_seconds,
                character_personalities=character_personalities,
                relationships=relationships,
                memories=memories,
                cultures=cultures,
                performance_context=performance_context,
            )
        except ToonScriptGenerationError as exc:
            raise HTTPException(status_code=502, detail=f"Script generation failed: {exc}")

        script = ToonScript(
            brand_id=brand.id,
            character_variant_id=variants[0].id,
            character_variant_ids=[str(v.id) for v in variants],
            source_type="idea", idea_text=idea,
            hook_line=result.get("hook_line"),
            tone=result.get("tone"),
            shots=result.get("shots"),
            total_duration_seconds=result.get("total_duration_seconds"),
            comedy_judgment=judge_script_comedy(result),
            generation_source="ai",
            status="draft",
        )
        session.add(script)
        session.commit()
        session.refresh(script)
        return _serialize_script(script)
    finally:
        session.close()


@router.get("/scripts")
def list_scripts(user_id: str, brand_id: str, character_variant_id: Optional[str] = None, status: Optional[str] = None):
    from app.db import SessionLocal
    from app.models.toon_script import ToonScript
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        query = session.query(ToonScript).filter_by(brand_id=brand.id)
        if character_variant_id:
            query = query.filter_by(character_variant_id=_uuid.UUID(character_variant_id))
        if status:
            query = query.filter_by(status=status)
        scripts = query.order_by(ToonScript.created_at.desc()).all()
        return [_serialize_script(s) for s in scripts]
    finally:
        session.close()


@router.get("/scripts/{script_id}")
def get_script(script_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        script = _get_script_owned(session, script_id, brand_id, user_id)
        return _serialize_script(script)
    finally:
        session.close()


@router.put("/scripts/{script_id}")
def update_script(script_id: str, body: dict):
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        script = _get_script_owned(session, script_id, brand_id, user_id)
        for field in ("hook_line", "dialogue", "scene_direction", "status", "tone", "shots", "total_duration_seconds"):
            if field in body:
                setattr(script, field, body[field])
        if "character_variant_id" in body:
            new_variant_id = body["character_variant_id"]
            if new_variant_id:
                _get_variant_owned(session, new_variant_id, brand_id, user_id)
                script.character_variant_id = _uuid.UUID(new_variant_id)
            else:
                script.character_variant_id = None
        if "background_id" in body:
            new_background_id = body["background_id"]
            if new_background_id:
                _get_background_owned(session, new_background_id, brand_id, user_id)
                script.background_id = _uuid.UUID(new_background_id)
            else:
                script.background_id = None
        session.commit()
        session.refresh(script)
        return _serialize_script(script)
    finally:
        session.close()


@router.delete("/scripts/{script_id}")
def delete_script(script_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        script = _get_script_owned(session, script_id, brand_id, user_id)
        script.status = "archived"
        session.commit()
        return {"status": "archived"}
    finally:
        session.close()


@router.post("/scripts/{script_id}/regenerate")
def regenerate_script(script_id: str, body: dict):
    """Re-runs AI generation for an existing script and updates it IN
    PLACE (same id, same row) rather than creating a duplicate — lets a
    user get a fresh take on a draft they don't like without deleting and
    re-suggesting by hand. Only works for scripts with a stored AI source
    to regenerate from: persona/cluster (source_type + source_id, still
    live) or idea (idea_text). Manual scripts, or idea scripts created
    before idea_text was tracked, have nothing to regenerate from.

    Known simplification: episode-continuation scripts (generate_toon_
    script_continuing_episode) also set source_type="idea" and now store
    idea_text too, but regenerating one here re-runs the PLAIN idea-based
    generator, not the continuation-aware one — it won't re-ground itself
    in the episode's prior parts. Flagged rather than silently dropping
    that context with no trace."""
    from app.db import SessionLocal
    from app.models.character_variant import CharacterVariant
    from app.services.culturetoon_script import (
        generate_toon_script, generate_toon_script_from_idea, judge_script_comedy,
        ToonScriptGenerationError, TONE_OPTIONS as _TONES,
    )

    user_id = body.get("user_id")
    brand_id = body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    tone = body.get("tone")
    if tone is not None and tone not in _TONES:
        raise HTTPException(status_code=400, detail=f"tone must be one of {_TONES}")

    session = SessionLocal()
    try:
        _get_brand_owned(session, brand_id, user_id)
        script = _get_script_owned(session, script_id, brand_id, user_id)

        cast_ids = list(script.character_variant_ids or ([str(script.character_variant_id)] if script.character_variant_id else []))
        if not cast_ids:
            raise HTTPException(status_code=400, detail="Script has no cast to regenerate for")
        variants_by_id = {
            str(v.id): v for v in session.query(CharacterVariant).filter(
                CharacterVariant.id.in_([_uuid.UUID(v) for v in cast_ids])
            ).all()
        }
        variants = [variants_by_id[vid] for vid in cast_ids if vid in variants_by_id]
        if not variants:
            raise HTTPException(status_code=400, detail="This script's cast no longer exists")

        effective_tone = tone or script.tone or "funny"
        num_shots = len(script.shots) if script.shots else 4
        target_duration_seconds = script.total_duration_seconds or 12
        character_personalities, relationships, memories, cultures, performance_context = _gather_script_generation_context(
            session, brand_id, variants, script.idea_text or ""
        )
        # Auto-fed in whenever the stored judgment failed the bar — closes
        # the loop from judge_script_comedy's own feedback without the
        # frontend needing to pass anything extra; the "Regenerate with
        # this feedback" button relies on this happening automatically.
        # Combined with an optional human-typed note (e.g. "make the ending
        # bigger") — either, both, or neither may be present.
        prior_judgment = script.comedy_judgment or {}
        ai_feedback = prior_judgment.get("feedback") if prior_judgment.get("passes_bar") is False else None
        human_note = (body.get("note") or "").strip() or None
        feedback_parts = []
        if ai_feedback:
            feedback_parts.append(f"AI comedy critic said: {ai_feedback}")
        if human_note:
            feedback_parts.append(f"The user specifically asked: {human_note}")
        critique_feedback = " | ".join(feedback_parts) or None
        # The actual previous draft, so the revision prompt has something
        # concrete to anchor to and edit minimally instead of rewriting the
        # whole story — see _build_prompt_from_context's REVISION MODE.
        previous_draft = (
            {"hook_line": script.hook_line, "shots": script.shots}
            if critique_feedback and script.shots else None
        )

        try:
            if script.source_type in ("persona", "cluster") and script.source_id is not None:
                source = _fetch_trend_source(session, script.source_type, script.source_id)
                if not source:
                    raise HTTPException(
                        status_code=404,
                        detail=f"The {script.source_type} this script was grounded in no longer exists — can't regenerate from it",
                    )
                result = generate_toon_script(
                    source, variants=variants, tone=effective_tone,
                    num_shots=num_shots, target_duration_seconds=target_duration_seconds,
                    character_personalities=character_personalities, relationships=relationships,
                    memories=memories, cultures=cultures, performance_context=performance_context,
                    critique_feedback=critique_feedback, previous_draft=previous_draft,
                )
            elif script.idea_text:
                result = generate_toon_script_from_idea(
                    script.idea_text, variants=variants, tone=effective_tone,
                    num_shots=num_shots, target_duration_seconds=target_duration_seconds,
                    character_personalities=character_personalities, relationships=relationships,
                    memories=memories, cultures=cultures, performance_context=performance_context,
                    critique_feedback=critique_feedback, previous_draft=previous_draft,
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="This script has no stored AI source to regenerate from — edit it directly, or create a new one instead.",
                )
        except ToonScriptGenerationError as exc:
            raise HTTPException(status_code=502, detail=f"Regeneration failed: {exc}")

        script.hook_line = result.get("hook_line")
        script.tone = result.get("tone")
        script.shots = result.get("shots")
        script.total_duration_seconds = result.get("total_duration_seconds")
        script.comedy_judgment = judge_script_comedy(result)
        script.status = "draft"
        session.commit()
        session.refresh(script)
        return _serialize_script(script)
    finally:
        session.close()


@router.post("/scripts/{script_id}/generate-background")
def generate_script_background(script_id: str, body: dict):
    """Generates a background FROM this script's own scene setting —
    scripts drive backgrounds, not the reverse (previously backgrounds were
    a name-only gallery created with no relationship to any script at all).
    Creates a new ToonBackground (kept in the brand's reusable pool, same
    as before — other scripts/toons can still pick it directly) and points
    this script at it, so a Toon built from this script can default to
    inheriting it."""
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        script = _get_script_owned(session, script_id, brand_id, user_id)
        # Derive a real physical setting (a PLACE) from the script rather
        # than reusing its shots' character-action lines. Confirmed live
        # 2026-09-01: every existing Location row had the script's comedic
        # hook as its name and a run-on list of actions as its description,
        # which then fed the video prompt as "Set in <joke>: <actions>" —
        # incoherent scene direction on every generation. Fails OPEN to the
        # old behavior: a background is still better than a hard 502 if the
        # LLM is down, matching this codebase's pipeline-node convention.
        derived = None
        try:
            from app.services.culturetoon_script import derive_scene_setting
            derived = derive_scene_setting(script)
        except Exception:
            logger.warning(
                "Could not derive a scene setting for script %s — falling back to its raw "
                "scene direction / shot actions", script_id, exc_info=True,
            )

        scene = derived["description"] if derived else _script_scene_description(script)
        extra_description = (body.get("extra_description") or "").strip()
        # extra_description leads rather than trails: it's the user's own
        # deliberate correction, while `scene` is often just the shots'
        # character-action sentences (confirmed live: e.g. "John looks
        # around confused... Asian version of Kumar shakes his head...")
        # which describe people's behavior, not the venue — burying the
        # one real scene cue after four sentences of that let it get lost
        # or contradicted against the background prompt's own "no people"
        # instruction.
        description = " ".join(p for p in [extra_description, scene] if p)
        if not description:
            raise HTTPException(
                status_code=400,
                detail="This script has no scene direction or shot actions to generate a background from — "
                       "add one, or pass extra_description.",
            )
        art_style = body.get("art_style") or DEFAULT_ART_STYLE
        # Prefer the derived LOCATION name over script.hook_line — the hook
        # is the episode's comedic premise ("Wikipedia searches for King
        # Harald V go hilariously wrong"), never a place, and it was ending
        # up as the Location's name on every row.
        default_name = ((derived["name"] if derived else None) or script.hook_line or description)[:120]
        background, budget_warning = _generate_background_asset(
            session, brand, user_id, description, art_style, body.get("name"), default_name,
            country=body.get("country") or (derived["country"] if derived else None),
        )
        script.background_id = background.id
        session.commit()
        session.refresh(background)
        serialized = _serialize_background(background)
        if budget_warning:
            serialized["budget_warning"] = budget_warning
        return serialized
    finally:
        session.close()


@router.post("/backgrounds/generate")
def generate_background(body: dict):
    """AI-generates a background directly into the brand's reusable pool —
    no script required. Added because the only way to populate the
    Backgrounds tab's "build 5-10 and rotate them" gallery was manual image
    upload, with zero AI assist, even though the exact same generation path
    already existed for the script-tied flow (generate_script_background).
    Shares _generate_background_asset with that route rather than
    duplicating the prompt/generate/save block."""
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    description = (body.get("description") or "").strip()
    if not user_id or not brand_id or not description:
        raise HTTPException(status_code=400, detail="user_id, brand_id and description are required")
    art_style = body.get("art_style") or DEFAULT_ART_STYLE
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        background, budget_warning = _generate_background_asset(
            session, brand, user_id, description, art_style, body.get("name"), description[:120],
            country=body.get("country"),
        )
        session.commit()
        session.refresh(background)
        serialized = _serialize_background(background)
        if budget_warning:
            serialized["budget_warning"] = budget_warning
        return serialized
    finally:
        session.close()


def _generate_background_asset(session, brand, user_id: str, description: str, art_style: str,
                                requested_name: Optional[str], default_name: str,
                                country: Optional[str] = None):
    """Shared by generate_script_background and generate_background: checks
    budget, builds the prompt, generates + stores the image, records usage,
    and adds a new ToonBackground to the session (uncommitted — callers
    commit, since generate_script_background also needs to point its script
    at the new row in the same transaction). Returns (background,
    budget_warning) — warning is None unless the brand is approaching its
    configured budget. art_style is stored as visual_style on the created
    row (it's already validated against ART_STYLES below), so a generated
    location remembers the style it was illustrated in."""
    if art_style not in ART_STYLES:
        raise HTTPException(status_code=400, detail=f"Unknown art_style: {art_style}")
    budget_warning = _check_budget_or_raise(session, brand)

    prompt = _build_background_prompt(description, art_style)
    from app.media.image_hybrid import HybridImageProvider
    try:
        result = HybridImageProvider().generate(prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Background generation failed: {exc}")

    from app.models.toon_background import ToonBackground
    ext = "jpg" if result.content_type == "image/jpeg" else "png"
    background_id = _uuid.uuid4()
    path = f"culturetoons/{brand.id}/backgrounds/{background_id}.{ext}"
    from app.services.culturetoon_media import save_image, ImageUploadError
    try:
        url = save_image(result.asset_bytes, result.content_type, path)
    except ImageUploadError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to store generated background: {exc}")

    from app.services.culturetoon_usage import record_usage
    record_usage(
        session, user_id=user_id, brand_id=brand.id, provider="hybrid_image",
        generation_type="background_image", cost_usd=result.cost_usd,
    )

    name = (requested_name or "").strip() or default_name
    background = ToonBackground(
        id=background_id, brand_id=brand.id, name=name,
        image_url=url, description=description,
        visual_style=art_style, country=country,
    )
    session.add(background)
    return background, budget_warning


# ── toons ─────────────────────────────────────────────────────────────────

@router.post("/toons")
def create_toon(body: dict):
    from app.db import SessionLocal
    from app.models.toon import Toon
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    character_variant_id = body.get("character_variant_id")
    script_id = body.get("script_id")
    if not user_id or not brand_id or not character_variant_id or not script_id:
        raise HTTPException(status_code=400, detail="user_id, brand_id, character_variant_id and script_id are required")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        _get_variant_owned(session, character_variant_id, brand_id, user_id)
        _get_script_owned(session, script_id, brand_id, user_id)
        background_id = body.get("background_id")
        if background_id:
            _get_background_owned(session, background_id, brand_id, user_id)

        toon = Toon(
            brand_id=brand.id,
            character_variant_id=_uuid.UUID(character_variant_id),
            script_id=_uuid.UUID(script_id),
            background_id=_uuid.UUID(background_id) if background_id else None,
            title=body.get("title"),
            status="idea",
        )
        session.add(toon)
        session.commit()
        session.refresh(toon)
        return _serialize_toon(toon)
    finally:
        session.close()


@router.get("/toons")
def list_toons(user_id: str, brand_id: str, status: Optional[str] = None):
    from app.db import SessionLocal
    from app.models.toon import Toon
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        query = session.query(Toon).filter_by(brand_id=brand.id)
        if status:
            query = query.filter_by(status=status)
        toons = query.order_by(Toon.created_at.desc()).all()
        return [_serialize_toon(t) for t in toons]
    finally:
        session.close()


@router.get("/toons/{toon_id}")
def get_toon(toon_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        toon = _get_toon_owned(session, toon_id, brand_id, user_id)
        return _serialize_toon(toon)
    finally:
        session.close()


@router.put("/toons/{toon_id}")
def update_toon(toon_id: str, body: dict):
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        toon = _get_toon_owned(session, toon_id, brand_id, user_id)
        if "background_id" in body:
            background_id = body["background_id"]
            if background_id:
                _get_background_owned(session, background_id, brand_id, user_id)
                toon.background_id = _uuid.UUID(background_id)
            else:
                toon.background_id = None
        for field in ("title", "final_video_url", "status", "platform", "notes",
                      "raw_video_url", "clip_video_urls", "generation_error"):
            if field in body:
                setattr(toon, field, body[field])
        if "posted_at" in body:
            raw = body["posted_at"]
            toon.posted_at = datetime.fromisoformat(raw) if raw else None
        elif body.get("status") == "posted" and not toon.posted_at:
            toon.posted_at = datetime.utcnow()
        session.commit()
        session.refresh(toon)
        return _serialize_toon(toon)
    finally:
        session.close()


@router.delete("/toons/{toon_id}")
def delete_toon(toon_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        toon = _get_toon_owned(session, toon_id, brand_id, user_id)
        toon.status = "archived"
        session.commit()
        return {"status": "archived"}
    finally:
        session.close()


def _resolve_script_cast(session, script, toon):
    from app.models.character_variant import CharacterVariant
    cast_ids = [str(v) for v in (script.character_variant_ids or [])]
    if not cast_ids and script.character_variant_id:
        cast_ids = [str(script.character_variant_id)]
    if not cast_ids:
        cast_ids = [str(toon.character_variant_id)]
    variants_by_id = {
        str(v.id): v for v in session.query(CharacterVariant).filter(
            CharacterVariant.id.in_([_uuid.UUID(v) for v in cast_ids])
        ).all()
    }
    return [variants_by_id[vid] for vid in cast_ids if vid in variants_by_id]


@router.post("/toons/{toon_id}/generate-video")
def generate_toon_video(toon_id: str, body: dict, background_tasks: BackgroundTasks):
    """Backgrounded — both providers' generation calls run well past any
    HTTP gateway timeout (Kling Omni up to ~6 min, self-hosted's RunPod
    Serverless call is comparably slow on a cold worker).

    provider ("kling_omni" | "self_hosted") is optional — when omitted,
    auto-picks self_hosted if the toon's own character variant already has
    a ready LoRA, else falls back to kling_omni (today's only behavior,
    unchanged for every variant that hasn't been through Phase 1's LoRA
    training yet). The Kling readiness check stays exactly as before
    (the toon's own variant only) — self-hosted's readiness check covers
    the script's FULL cast instead, since generate_toon_video_selfhosted's
    resolve_ready_lora requires every cast member to have a trained LoRA
    even though only the primary one is visually grounded."""
    from app.db import SessionLocal
    from app.services.culturetoon_video import generate_video_for_toon
    from app.services.culturetoon_selfhosted_video import generate_video_for_toon_selfhosted

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        toon = _get_toon_owned(session, toon_id, brand_id, user_id)
        budget_warning = _check_budget_or_raise(session, brand)
        from app.models.toon_script import ToonScript
        from app.models.character_variant import CharacterVariant
        script = session.query(ToonScript).filter_by(id=toon.script_id).first()
        variant = session.query(CharacterVariant).filter_by(id=toon.character_variant_id).first()
        if not script or not script.shots:
            raise HTTPException(status_code=400, detail="Toon's script has no shot data — generate/select a shot-structured script first")
        if not variant:
            raise HTTPException(status_code=400, detail="Character variant not found")

        from app.services.culturetoon_selfhosted_video import use_ltx25
        ltx25 = use_ltx25()

        # LTX-2.5 carries character identity with a composite first-frame
        # anchor built from the cast's real portraits, so a trained LoRA is
        # not required — or even used. Gating on lora_status under 2.5 would
        # permanently route every character without one to Kling, which is
        # the opposite of the intent. What it actually needs is a portrait
        # per character.
        if ltx25:
            provider = body.get("provider") or ("self_hosted" if variant.image_url else "kling_omni")
        else:
            provider = body.get("provider") or ("self_hosted" if variant.lora_status == "ready" else "kling_omni")

        if provider == "self_hosted":
            cast = _resolve_script_cast(session, script, toon)
            if not cast:
                raise HTTPException(status_code=400, detail="Script has no resolvable cast to generate for")
            if ltx25:
                missing_portraits = [v.name for v in cast if not v.image_url]
                if missing_portraits:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Character(s) have no portrait image to anchor identity on: "
                            f"{', '.join(missing_portraits)}. Generate or upload one first."
                        ),
                    )
            else:
                not_ready = [v.name for v in cast if v.lora_status != "ready"]
                if not_ready:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Character(s) not ready for self-hosted generation (no trained LoRA): {', '.join(not_ready)}",
                    )
        else:
            if variant.element_status != "ready":
                raise HTTPException(status_code=400, detail="Character variant is not a ready Kling element — register it first")
            from app.services.culturetoon_script import KLING_MAX_SHOTS, KLING_MAX_TOTAL_SECONDS
            script_seconds = script.total_duration_seconds or sum(s.get("duration_seconds", 0) for s in script.shots)
            if len(script.shots) > KLING_MAX_SHOTS or script_seconds > KLING_MAX_TOTAL_SECONDS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"This script ({len(script.shots)} shots, {script_seconds}s) is too long for Kling Omni "
                        f"(max {KLING_MAX_SHOTS} shots / {KLING_MAX_TOTAL_SECONDS}s) — switch to self-hosted "
                        "generation or shorten the script."
                    ),
                )

        toon.status = "animating"
        toon.generation_error = None
        session.commit()
    finally:
        session.close()

    if provider == "self_hosted":
        background_tasks.add_task(generate_video_for_toon_selfhosted, user_id=user_id, toon_id=toon_id)
    else:
        background_tasks.add_task(generate_video_for_toon, user_id=user_id, toon_id=toon_id)
    response = {"status": "generation_started", "provider": provider}
    if budget_warning:
        response["budget_warning"] = budget_warning
    return response


@router.post("/toons/{toon_id}/publish")
def publish_toon(toon_id: str, body: dict, background_tasks: BackgroundTasks):
    """Publishes a ready Toon to a connected social account for this
    brand — the real "where it's posted" flow this product was missing
    (see harmonic-mixing-flame.md's Phase 3), wired onto the same
    ConnectedAccount/OAuth infra the main trend-driven product already
    uses (app/social/service.py's resolve_active_account, already
    character_brand_id-aware). Backgrounded like publish_content_post:
    the actual publish call downloads+re-uploads the finished video, which
    can run past a typical HTTP gateway timeout."""
    from app.db import SessionLocal
    from app.models.toon_post import ToonPost
    from app.social.service import resolve_active_account, publish_toon_and_record

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    platform = body.get("platform")
    if not user_id or not brand_id or not platform:
        raise HTTPException(status_code=400, detail="user_id, brand_id and platform are required")

    session = SessionLocal()
    try:
        toon = _get_toon_owned(session, toon_id, brand_id, user_id)
        if not toon.final_video_url:
            raise HTTPException(status_code=400, detail="This toon has no final video selected yet")

        account = resolve_active_account(session, _uuid.UUID(user_id), platform, character_brand_id=_uuid.UUID(brand_id))
        if not account:
            raise HTTPException(
                status_code=400,
                detail=f"No {platform} account connected for this brand — connect one first",
            )

        post = ToonPost(
            toon_id=toon.id, brand_id=toon.brand_id, user_id=_uuid.UUID(user_id),
            platform=platform, status="pending",
        )
        session.add(post)
        session.commit()
        session.refresh(post)
        post_id = str(post.id)
        result = _serialize_toon_post(post)
    finally:
        session.close()

    background_tasks.add_task(publish_toon_and_record, toon_post_id=post_id)
    return result


@router.get("/toons/{toon_id}/posts")
def list_toon_posts(toon_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    from app.models.toon_post import ToonPost

    session = SessionLocal()
    try:
        toon = _get_toon_owned(session, toon_id, brand_id, user_id)
        posts = session.query(ToonPost).filter_by(toon_id=toon.id).order_by(ToonPost.created_at.desc()).all()
        return [_serialize_toon_post(p) for p in posts]
    finally:
        session.close()


@router.post("/toon-posts/{toon_post_id}/refresh")
def refresh_toon_post(toon_post_id: str, body: dict, background_tasks: BackgroundTasks):
    """Re-fetches performance metrics for an already-published ToonPost —
    the CultureToons analogue of POST /api/content-posts/{id}/refresh."""
    from app.db import SessionLocal
    from app.social.service import fetch_toon_and_record

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        _get_toon_post_owned(session, toon_post_id, brand_id, user_id)
    finally:
        session.close()

    background_tasks.add_task(fetch_toon_and_record, toon_post_id=toon_post_id)
    return {"status": "refresh_started"}


# ── Episodes (multi-part stories stitched from several Toons) ──────────────

@router.post("/episodes")
def create_episode(body: dict):
    from app.db import SessionLocal
    from app.models.toon_episode import ToonEpisode
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        episode = ToonEpisode(brand_id=brand.id, title=body.get("title"), status="draft")
        session.add(episode)
        session.commit()
        session.refresh(episode)
        return _serialize_episode(session, episode)
    finally:
        session.close()


@router.get("/episodes")
def list_episodes(user_id: str, brand_id: str, status: Optional[str] = None):
    from app.db import SessionLocal
    from app.models.toon_episode import ToonEpisode
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        query = session.query(ToonEpisode).filter_by(brand_id=brand.id)
        if status:
            query = query.filter_by(status=status)
        episodes = query.order_by(ToonEpisode.created_at.desc()).all()
        return [_serialize_episode(session, e) for e in episodes]
    finally:
        session.close()


@router.get("/episodes/{episode_id}")
def get_episode(episode_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        return _serialize_episode(session, episode)
    finally:
        session.close()


@router.put("/episodes/{episode_id}")
def update_episode(episode_id: str, body: dict):
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        for field in ("title", "status", "generation_error"):
            if field in body:
                setattr(episode, field, body[field])
        session.commit()
        session.refresh(episode)
        return _serialize_episode(session, episode)
    finally:
        session.close()


@router.post("/episodes/{episode_id}/parts")
def attach_episode_part(episode_id: str, body: dict):
    """Attaches an existing, standalone Toon (same brand) as the next part
    of this episode — a part IS a normal Toon, generated via the existing
    unchanged POST /toons/{id}/generate-video; this endpoint only assigns
    episode_id/part_order, it never creates or generates video itself."""
    from app.db import SessionLocal
    from app.models.toon import Toon
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    toon_id = body.get("toon_id")
    if not user_id or not brand_id or not toon_id:
        raise HTTPException(status_code=400, detail="user_id, brand_id and toon_id are required")
    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        toon = _get_toon_owned(session, toon_id, brand_id, user_id)
        if toon.episode_id is not None:
            raise HTTPException(
                status_code=400,
                detail="This toon is already attached to an episode — detach it first",
            )
        max_order = (
            session.query(Toon).filter_by(episode_id=episode.id)
            .order_by(Toon.part_order.desc()).first()
        )
        toon.episode_id = episode.id
        toon.part_order = (max_order.part_order + 1) if max_order and max_order.part_order is not None else 0
        session.commit()
        return _serialize_episode(session, episode)
    finally:
        session.close()


@router.post("/episodes/{episode_id}/parts/suggest-next")
def suggest_next_episode_part(episode_id: str, body: dict):
    """AI-suggests the next part's script grounded in a synopsis of every
    part already attached (see _episode_synopsis), so the story continues
    naturally instead of each part being written blind — then creates the
    script + a new Toon and attaches it as the episode's next part in one
    step, mirroring suggest_script_from_idea's create-and-return shape.
    Synchronous like the other suggest endpoints: one LLM call, the caller
    needs the result immediately to render it. Video generation for the new
    part is a separate step (POST /toons/{id}/generate-video), same as any
    other toon."""
    from app.db import SessionLocal
    from app.models.toon import Toon
    from app.models.toon_script import ToonScript
    from app.services.culturetoon_script import (
        generate_toon_script_continuing_episode, judge_script_comedy, ToonScriptGenerationError, TONE_OPTIONS as _TONES,
    )

    user_id = body.get("user_id")
    brand_id = body.get("brand_id")
    idea = (body.get("idea") or "").strip()
    tone = body.get("tone", "funny")

    if not user_id or not brand_id or not idea:
        raise HTTPException(status_code=400, detail="user_id, brand_id and idea are required")
    if not _extract_cast_ids(body):
        raise HTTPException(
            status_code=400,
            detail="character_variant_ids (or character_variant_id) is required — pick at least one real character",
        )
    if tone not in _TONES:
        raise HTTPException(status_code=400, detail=f"tone must be one of {_TONES}")
    num_shots, target_duration_seconds = _validate_script_generation_params(body)

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        variants = _resolve_cast(session, body, brand_id, user_id)
        prior_parts_summary = _episode_synopsis(session, episode)
        if not prior_parts_summary:
            raise HTTPException(
                status_code=400,
                detail="This episode has no parts with a generated script yet — attach or suggest a first part before continuing the story",
            )
        character_personalities, relationships, memories, cultures, performance_context = _gather_script_generation_context(
            session, brand_id, variants, idea
        )

        try:
            result = generate_toon_script_continuing_episode(
                prior_parts_summary, idea, variants, tone=tone,
                num_shots=num_shots, target_duration_seconds=target_duration_seconds,
                character_personalities=character_personalities, relationships=relationships,
                memories=memories, cultures=cultures, performance_context=performance_context,
            )
        except ToonScriptGenerationError as exc:
            raise HTTPException(status_code=502, detail=f"Script generation failed: {exc}")

        script = ToonScript(
            brand_id=brand.id,
            character_variant_id=variants[0].id,
            character_variant_ids=[str(v.id) for v in variants],
            source_type="idea", idea_text=idea,
            hook_line=result.get("hook_line"),
            tone=result.get("tone"),
            shots=result.get("shots"),
            total_duration_seconds=result.get("total_duration_seconds"),
            comedy_judgment=judge_script_comedy(result),
            generation_source="ai",
            status="draft",
        )
        session.add(script)
        session.commit()
        session.refresh(script)

        toon = Toon(
            brand_id=brand.id,
            character_variant_id=variants[0].id,
            script_id=script.id,
            title=result.get("hook_line"),
            status="idea",
        )
        session.add(toon)
        session.commit()
        session.refresh(toon)

        max_order = (
            session.query(Toon).filter_by(episode_id=episode.id)
            .order_by(Toon.part_order.desc()).first()
        )
        toon.episode_id = episode.id
        toon.part_order = (max_order.part_order + 1) if max_order and max_order.part_order is not None else 0
        session.commit()

        return _serialize_episode(session, episode)
    finally:
        session.close()


@router.delete("/episodes/{episode_id}/parts/{toon_id}")
def detach_episode_part(episode_id: str, toon_id: str, user_id: str, brand_id: str):
    """Detaches a part — the underlying Toon is untouched and simply
    becomes a normal standalone Toon again, never deleted."""
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        toon = _get_toon_owned(session, toon_id, brand_id, user_id)
        if toon.episode_id != episode.id:
            raise HTTPException(status_code=404, detail="This toon is not a part of this episode")
        toon.episode_id = None
        toon.part_order = None
        session.commit()
        return _serialize_episode(session, episode)
    finally:
        session.close()


@router.put("/episodes/{episode_id}/parts/reorder")
def reorder_episode_parts(episode_id: str, body: dict):
    from app.db import SessionLocal
    from app.models.toon import Toon
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    toon_ids = body.get("toon_ids")
    if not user_id or not brand_id or not isinstance(toon_ids, list):
        raise HTTPException(status_code=400, detail="user_id, brand_id and toon_ids (list) are required")
    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        current = session.query(Toon).filter_by(episode_id=episode.id).all()
        current_ids = {str(t.id) for t in current}
        if set(toon_ids) != current_ids:
            raise HTTPException(status_code=400, detail="toon_ids must match exactly this episode's current parts")
        by_id = {str(t.id): t for t in current}
        for i, tid in enumerate(toon_ids):
            by_id[tid].part_order = i
        session.commit()
        return _serialize_episode(session, episode)
    finally:
        session.close()


@router.post("/episodes/{episode_id}/stitch")
def stitch_episode_endpoint(episode_id: str, body: dict, background_tasks: BackgroundTasks):
    """Backgrounded — a 60-180s multi-part re-encode is heavier than any
    single existing ffmpeg step in this router, running well past a typical
    HTTP gateway timeout. Validates readiness synchronously first (matching
    generate_toon_video's pattern) so a not-ready episode 400s immediately
    instead of only failing after being backgrounded."""
    from app.db import SessionLocal
    from app.models.toon import Toon
    from app.services.culturetoon_episode import stitch_episode

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        parts = (
            session.query(Toon).filter_by(episode_id=episode.id)
            .order_by(Toon.part_order.asc()).all()
        )
        if len(parts) < 2:
            raise HTTPException(status_code=400, detail="An episode needs at least 2 parts before it can be stitched")
        missing = [str(p.part_order) for p in parts if not p.raw_video_url]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Part(s) at position(s) {', '.join(missing)} have no generated video yet",
            )

        episode.status = "stitching"
        episode.generation_error = None
        session.commit()
    finally:
        session.close()

    background_tasks.add_task(stitch_episode, user_id=user_id, episode_id=episode_id)
    return {"status": "stitching_started"}


@router.post("/episodes/{episode_id}/generate-clips")
def generate_episode_clips_endpoint(episode_id: str, body: dict, background_tasks: BackgroundTasks):
    """Cuts highlight candidate clips from a finished episode's stitched
    video for social media — separate opt-in step from stitch (extra ffmpeg
    cost not every stitch needs), reusing cut_clips() unmodified."""
    from app.db import SessionLocal
    from app.services.culturetoon_episode import generate_episode_clips

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        if not episode.final_video_url:
            raise HTTPException(status_code=400, detail="Stitch this episode first")
    finally:
        session.close()

    background_tasks.add_task(generate_episode_clips, user_id=user_id, episode_id=episode_id)
    return {"status": "clip_generation_started"}


# ── scenes ───────────────────────────────────────────────────────────────
# Independently-generated production units within a ToonEpisode — see
# app/models/toon_scene.py's docstring for how this relates to (and doesn't
# replace) the pre-existing Toon-parts stitching path.

def _serialize_scene(s) -> dict:
    return {
        "id": str(s.id), "episode_id": str(s.episode_id), "brand_id": str(s.brand_id),
        "scene_number": s.scene_number,
        "character_variant_ids": s.character_variant_ids or [],
        "background_id": str(s.background_id) if s.background_id else None,
        "action": s.action, "dialogue": s.dialogue, "expression": s.expression,
        "camera_direction": s.camera_direction, "duration_seconds": s.duration_seconds,
        "status": s.status, "video_url": s.video_url,
        "previous_video_urls": s.previous_video_urls or [],
        "kling_task_id": s.kling_task_id, "generation_error": s.generation_error,
        "generation_attempts": s.generation_attempts,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _get_scene_owned(session, scene_id: str, brand_id: str, user_id: str):
    from app.models.toon_scene import ToonScene
    brand = _get_brand_owned(session, brand_id, user_id)
    scene = session.query(ToonScene).filter_by(id=_uuid.UUID(scene_id)).first()
    if not scene or scene.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Scene not found")
    return scene


@router.post("/episodes/{episode_id}/scenes")
def create_scene(episode_id: str, body: dict):
    from app.db import SessionLocal
    from app.models.toon_scene import ToonScene

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    duration_seconds = body.get("duration_seconds", 4)
    if not isinstance(duration_seconds, int) or not (1 <= duration_seconds <= 15):
        raise HTTPException(status_code=400, detail="duration_seconds must be an integer between 1 and 15")

    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        cast_ids = body.get("character_variant_ids") or []
        for vid in cast_ids:
            _get_variant_owned(session, vid, brand_id, user_id)
        if body.get("background_id"):
            _get_background_owned(session, body["background_id"], brand_id, user_id)

        next_number = body.get("scene_number")
        if next_number is None:
            existing_max = (
                session.query(ToonScene).filter_by(episode_id=episode.id)
                .order_by(ToonScene.scene_number.desc()).first()
            )
            next_number = (existing_max.scene_number + 1) if existing_max else 1

        scene = ToonScene(
            episode_id=episode.id, brand_id=episode.brand_id, scene_number=next_number,
            character_variant_ids=cast_ids or None,
            background_id=_uuid.UUID(body["background_id"]) if body.get("background_id") else None,
            action=body.get("action"), dialogue=body.get("dialogue"), expression=body.get("expression"),
            camera_direction=body.get("camera_direction"), duration_seconds=duration_seconds,
        )
        session.add(scene)
        session.commit()
        session.refresh(scene)
        return _serialize_scene(scene)
    finally:
        session.close()


@router.post("/episodes/{episode_id}/scenes/from-script")
def create_scenes_from_script(episode_id: str, body: dict):
    """Convenience: breaks an existing shot-structured ToonScript's shots
    into one ToonScene per shot, appended after this episode's existing
    scenes — the natural mapping from "AI-suggested script" to "episode
    production plan" without hand-recreating every shot as a scene."""
    from app.db import SessionLocal
    from app.models.toon_scene import ToonScene
    from app.models.toon_script import ToonScript

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    script_id = body.get("script_id")
    if not user_id or not brand_id or not script_id:
        raise HTTPException(status_code=400, detail="user_id, brand_id and script_id are required")

    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        script = _get_script_owned(session, script_id, brand_id, user_id)
        if not script.shots:
            raise HTTPException(status_code=400, detail="This script has no shot data to convert into scenes")

        cast_ids = list(script.character_variant_ids or ([str(script.character_variant_id)] if script.character_variant_id else []))
        existing_max = (
            session.query(ToonScene).filter_by(episode_id=episode.id)
            .order_by(ToonScene.scene_number.desc()).first()
        )
        next_number = (existing_max.scene_number + 1) if existing_max else 1

        created = []
        for shot in script.shots:
            speaker_id = shot.get("speaker_variant_id")
            shot_cast = [speaker_id] if speaker_id else cast_ids
            scene = ToonScene(
                episode_id=episode.id, brand_id=episode.brand_id, scene_number=next_number,
                character_variant_ids=shot_cast or None, background_id=script.background_id,
                action=shot.get("action"), dialogue=shot.get("dialogue"), expression=shot.get("expression"),
                duration_seconds=shot.get("duration_seconds") or 4,
            )
            session.add(scene)
            created.append(scene)
            next_number += 1
        session.commit()
        for scene in created:
            session.refresh(scene)
        return [_serialize_scene(s) for s in created]
    finally:
        session.close()


@router.get("/episodes/{episode_id}/scenes")
def list_scenes(episode_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    from app.models.toon_scene import ToonScene
    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        scenes = (
            session.query(ToonScene).filter_by(episode_id=episode.id)
            .order_by(ToonScene.scene_number.asc()).all()
        )
        return [_serialize_scene(s) for s in scenes]
    finally:
        session.close()


@router.put("/scenes/{scene_id}")
def update_scene(scene_id: str, body: dict):
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    session = SessionLocal()
    try:
        scene = _get_scene_owned(session, scene_id, brand_id, user_id)
        if "duration_seconds" in body:
            d = body["duration_seconds"]
            if not isinstance(d, int) or not (1 <= d <= 15):
                raise HTTPException(status_code=400, detail="duration_seconds must be an integer between 1 and 15")
        for vid in body.get("character_variant_ids") or []:
            _get_variant_owned(session, vid, brand_id, user_id)
        for field in ("scene_number", "character_variant_ids", "background_id", "action",
                      "dialogue", "expression", "camera_direction", "duration_seconds"):
            if field in body:
                value = body[field]
                if field == "background_id" and value:
                    value = _uuid.UUID(value)
                setattr(scene, field, value)
        session.commit()
        session.refresh(scene)
        return _serialize_scene(scene)
    finally:
        session.close()


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: str, user_id: str, brand_id: str):
    """Hard delete — see ToonScene's docstring on why this differs from
    every other entity's soft-delete-via-is_active convention."""
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        scene = _get_scene_owned(session, scene_id, brand_id, user_id)
        session.delete(scene)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


@router.post("/scenes/{scene_id}/generate")
def generate_scene(scene_id: str, body: dict, background_tasks: BackgroundTasks):
    """Backgrounded, same reasoning as POST /toons/{id}/generate-video —
    a Kling call can run minutes, past any HTTP gateway timeout."""
    from app.db import SessionLocal
    from app.services.culturetoon_scene import generate_scene_video

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        scene = _get_scene_owned(session, scene_id, brand_id, user_id)
        budget_warning = _check_budget_or_raise(session, brand)
        if not scene.character_variant_ids:
            raise HTTPException(status_code=400, detail="Assign at least one character to this scene first")
        from app.models.character_variant import CharacterVariant
        variants = session.query(CharacterVariant).filter(
            CharacterVariant.id.in_([_uuid.UUID(v) for v in scene.character_variant_ids])
        ).all()
        not_ready = [v.name for v in variants if v.element_status != "ready"]
        if not_ready:
            raise HTTPException(status_code=400, detail=f"Character(s) not registered as a ready Kling element: {', '.join(not_ready)}")

        scene.status = "generating"
        scene.generation_error = None
        session.commit()
    finally:
        session.close()

    background_tasks.add_task(generate_scene_video, user_id=user_id, scene_id=scene_id)
    response = {"status": "generation_started"}
    if budget_warning:
        response["budget_warning"] = budget_warning
    return response


@router.post("/episodes/{episode_id}/assemble-scenes")
def assemble_episode_from_scenes_endpoint(episode_id: str, body: dict, background_tasks: BackgroundTasks):
    """The Scene-based analogue of POST /episodes/{id}/stitch — assembles
    from ready ToonScenes instead of Toon parts."""
    from app.db import SessionLocal
    from app.models.toon_scene import ToonScene
    from app.services.culturetoon_episode import assemble_episode_from_scenes

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        episode = _get_episode_owned(session, episode_id, brand_id, user_id)
        ready_count = (
            session.query(ToonScene).filter_by(episode_id=episode.id, status="ready").count()
        )
        if ready_count < 1:
            raise HTTPException(status_code=400, detail="No ready scenes to assemble — generate at least one scene's video first")

        episode.status = "stitching"
        episode.generation_error = None
        session.commit()
    finally:
        session.close()

    background_tasks.add_task(assemble_episode_from_scenes, user_id=user_id, episode_id=episode_id)
    return {"status": "assembly_started"}


# ── shots ────────────────────────────────────────────────────────────────
# Cinematic production units within a ToonScene — see
# app/models/toon_shot.py's docstring for how this relates to (and doesn't
# replace) the pre-existing single-shot-per-Scene generation path
# (generate_scene above). A Scene simple enough to be one clip can stay
# that way; a Scene that needs real coverage (establishing, entrance,
# reaction, close-up, punchline...) decomposes into these instead.

def _serialize_shot(s) -> dict:
    return {
        "id": str(s.id), "scene_id": str(s.scene_id), "brand_id": str(s.brand_id),
        "shot_number": s.shot_number, "shot_type": s.shot_type, "duration_seconds": s.duration_seconds,
        "character_variant_ids": s.character_variant_ids or [],
        "background_id": str(s.background_id) if s.background_id else None,
        "action": s.action, "emotion": s.emotion, "dialogue": s.dialogue, "comedic_beat": s.comedic_beat,
        "camera_framing": s.camera_framing, "camera_angle": s.camera_angle, "camera_movement": s.camera_movement,
        "lens": s.lens, "composition": s.composition, "lighting": s.lighting,
        "visual_prompt": s.visual_prompt, "motion_prompt": s.motion_prompt, "audio_notes": s.audio_notes,
        "reference_assets": s.reference_assets or [],
        "provider": s.provider, "model": s.model,
        "generation_status": s.generation_status, "generation_attempts": s.generation_attempts,
        "generated_asset_id": s.generated_asset_id, "previous_asset_ids": s.previous_asset_ids or [],
        "kling_task_id": s.kling_task_id, "generation_error": s.generation_error,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _get_shot_owned(session, shot_id: str, brand_id: str, user_id: str):
    from app.models.toon_shot import ToonShot
    brand = _get_brand_owned(session, brand_id, user_id)
    shot = session.query(ToonShot).filter_by(id=_uuid.UUID(shot_id)).first()
    if not shot or shot.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Shot not found")
    return shot


_SHOT_EDITABLE_FIELDS = (
    "shot_number", "shot_type", "duration_seconds", "character_variant_ids", "background_id",
    "action", "emotion", "dialogue", "comedic_beat", "camera_framing", "camera_angle",
    "camera_movement", "lens", "composition", "lighting", "audio_notes",
)


def _validate_shot_fields(body: dict) -> None:
    from app.models.toon_shot import SHOT_TYPES, CAMERA_MOVEMENTS, COMEDIC_BEATS, MIN_SHOT_DURATION_SECONDS, MAX_SHOT_DURATION_SECONDS
    if body.get("shot_type") is not None and body["shot_type"] not in SHOT_TYPES:
        raise HTTPException(status_code=400, detail=f"shot_type must be one of {SHOT_TYPES}")
    if body.get("camera_movement") is not None and body["camera_movement"] not in CAMERA_MOVEMENTS:
        raise HTTPException(status_code=400, detail=f"camera_movement must be one of {CAMERA_MOVEMENTS}")
    if body.get("comedic_beat") is not None and body["comedic_beat"] not in COMEDIC_BEATS:
        raise HTTPException(status_code=400, detail=f"comedic_beat must be one of {COMEDIC_BEATS}")
    if body.get("duration_seconds") is not None:
        d = body["duration_seconds"]
        if not isinstance(d, int) or not (MIN_SHOT_DURATION_SECONDS <= d <= MAX_SHOT_DURATION_SECONDS):
            raise HTTPException(status_code=400, detail=f"duration_seconds must be an integer between {MIN_SHOT_DURATION_SECONDS} and {MAX_SHOT_DURATION_SECONDS}")


@router.post("/scenes/{scene_id}/shots")
def create_shot(scene_id: str, body: dict):
    from app.db import SessionLocal
    from app.models.toon_shot import ToonShot

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    _validate_shot_fields(body)

    session = SessionLocal()
    try:
        scene = _get_scene_owned(session, scene_id, brand_id, user_id)
        for vid in body.get("character_variant_ids") or []:
            _get_variant_owned(session, vid, brand_id, user_id)
        if body.get("background_id"):
            _get_background_owned(session, body["background_id"], brand_id, user_id)

        next_number = body.get("shot_number")
        if next_number is None:
            existing_max = (
                session.query(ToonShot).filter_by(scene_id=scene.id)
                .order_by(ToonShot.shot_number.desc()).first()
            )
            next_number = (existing_max.shot_number + 1) if existing_max else 1

        shot = ToonShot(
            scene_id=scene.id, brand_id=scene.brand_id, shot_number=next_number,
            shot_type=body.get("shot_type") or "medium", duration_seconds=body.get("duration_seconds") or 3,
            character_variant_ids=body.get("character_variant_ids") or None,
            background_id=_uuid.UUID(body["background_id"]) if body.get("background_id") else None,
            action=body.get("action"), emotion=body.get("emotion"), dialogue=body.get("dialogue"),
            comedic_beat=body.get("comedic_beat"), camera_framing=body.get("camera_framing"),
            camera_angle=body.get("camera_angle"), camera_movement=body.get("camera_movement"),
            lens=body.get("lens"), composition=body.get("composition"), lighting=body.get("lighting"),
            audio_notes=body.get("audio_notes"),
        )
        session.add(shot)
        session.commit()
        session.refresh(shot)
        return _serialize_shot(shot)
    finally:
        session.close()


@router.post("/scenes/{scene_id}/shots/plan")
def plan_scene_shots(scene_id: str, body: dict):
    """The "Generate Storyboard" step — AI (CinematicDirector, see
    app/services/culturetoon_cinematic_director.py) plans a shot sequence
    for this scene and persists it as real, editable ToonShot rows (status
    "idea", no video yet) so the user can review/edit before generating any
    clips. Appends after this scene's existing shots rather than replacing
    them, same convention as create_scenes_from_script — regenerating the
    whole storyboard from scratch is just deleting the old shots first."""
    from app.db import SessionLocal
    from app.models.toon_shot import ToonShot
    from app.models.character_variant import CharacterVariant
    from app.models.toon_background import ToonBackground
    from app.services.culturetoon_cinematic_director import plan_shots, CinematicDirectorError

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        scene = _get_scene_owned(session, scene_id, brand_id, user_id)
        cast_ids = list(scene.character_variant_ids or [])
        if not cast_ids:
            raise HTTPException(status_code=400, detail="This scene has no cast — assign at least one character before planning shots")
        variants = session.query(CharacterVariant).filter(CharacterVariant.id.in_([_uuid.UUID(v) for v in cast_ids])).all()
        cast = [{"variant_id": str(v.id), "name": v.name, "description": v.description} for v in variants]

        location_description = ""
        if scene.background_id:
            background = session.query(ToonBackground).filter_by(id=scene.background_id).first()
            if background:
                location_description = background.description or background.name

        scene_summary = (body.get("scene_summary") or "").strip() or scene.action or scene.dialogue or "A scene between the cast above"
        tone = body.get("tone") or "funny"
        target_duration_seconds = body.get("target_duration_seconds") or 20

        try:
            planned = plan_shots(
                scene_summary, cast, relationship_context=body.get("relationship_context") or "",
                location_description=location_description, tone=tone, target_duration_seconds=target_duration_seconds,
            )
        except CinematicDirectorError as exc:
            raise HTTPException(status_code=502, detail=f"Storyboard planning failed: {exc}")

        existing_max = (
            session.query(ToonShot).filter_by(scene_id=scene.id)
            .order_by(ToonShot.shot_number.desc()).first()
        )
        next_number = (existing_max.shot_number + 1) if existing_max else 1

        created = []
        for planned_shot in planned:
            shot = ToonShot(
                scene_id=scene.id, brand_id=scene.brand_id, shot_number=next_number,
                shot_type=planned_shot["shot_type"], duration_seconds=planned_shot["duration_seconds"],
                character_variant_ids=planned_shot["character_variant_ids"] or None,
                action=planned_shot["action"], emotion=planned_shot["emotion"], dialogue=planned_shot["dialogue"],
                comedic_beat=planned_shot["comedic_beat"], camera_framing=planned_shot["camera_framing"],
                camera_angle=planned_shot["camera_angle"], camera_movement=planned_shot["camera_movement"],
                lens=planned_shot["lens"], composition=planned_shot["composition"], lighting=planned_shot["lighting"],
            )
            session.add(shot)
            created.append(shot)
            next_number += 1
        session.commit()
        for shot in created:
            session.refresh(shot)
        return [_serialize_shot(s) for s in created]
    finally:
        session.close()


@router.get("/scenes/{scene_id}/shots")
def list_shots(scene_id: str, user_id: str, brand_id: str):
    from app.db import SessionLocal
    from app.models.toon_shot import ToonShot
    session = SessionLocal()
    try:
        scene = _get_scene_owned(session, scene_id, brand_id, user_id)
        shots = (
            session.query(ToonShot).filter_by(scene_id=scene.id)
            .order_by(ToonShot.shot_number.asc()).all()
        )
        return [_serialize_shot(s) for s in shots]
    finally:
        session.close()


@router.put("/shots/{shot_id}")
def update_shot(shot_id: str, body: dict):
    from app.db import SessionLocal
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    _validate_shot_fields(body)
    session = SessionLocal()
    try:
        shot = _get_shot_owned(session, shot_id, brand_id, user_id)
        for vid in body.get("character_variant_ids") or []:
            _get_variant_owned(session, vid, brand_id, user_id)
        if body.get("background_id"):
            _get_background_owned(session, body["background_id"], brand_id, user_id)
        for field in _SHOT_EDITABLE_FIELDS:
            if field in body:
                value = body[field]
                if field == "background_id" and value:
                    value = _uuid.UUID(value)
                setattr(shot, field, value)
        session.commit()
        session.refresh(shot)
        return _serialize_shot(shot)
    finally:
        session.close()


@router.delete("/shots/{shot_id}")
def delete_shot(shot_id: str, user_id: str, brand_id: str):
    """Hard delete — same reasoning as ToonScene: a shot is disposable
    storyboard-authoring scaffolding, not a reusable resource."""
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        shot = _get_shot_owned(session, shot_id, brand_id, user_id)
        session.delete(shot)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


@router.post("/shots/{shot_id}/generate")
def generate_shot(shot_id: str, body: dict, background_tasks: BackgroundTasks):
    """Backgrounded, same reasoning as every other Kling-call route in this
    file — a generation can run minutes, past any HTTP gateway timeout."""
    from app.db import SessionLocal
    from app.services.culturetoon_shot import generate_shot_video

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        shot = _get_shot_owned(session, shot_id, brand_id, user_id)
        budget_warning = _check_budget_or_raise(session, brand)
        if shot.character_variant_ids:
            from app.models.character_variant import CharacterVariant
            variants = session.query(CharacterVariant).filter(
                CharacterVariant.id.in_([_uuid.UUID(v) for v in shot.character_variant_ids])
            ).all()
            not_ready = [v.name for v in variants if v.element_status != "ready"]
            if not_ready:
                raise HTTPException(status_code=400, detail=f"Character(s) not registered as a ready Kling element: {', '.join(not_ready)}")

        shot.generation_status = "generating"
        shot.generation_error = None
        session.commit()
    finally:
        session.close()

    background_tasks.add_task(generate_shot_video, user_id=user_id, shot_id=shot_id)
    response = {"status": "generation_started"}
    if budget_warning:
        response["budget_warning"] = budget_warning
    return response


@router.post("/scenes/{scene_id}/assemble-shots")
def assemble_scene_from_shots_endpoint(scene_id: str, body: dict, background_tasks: BackgroundTasks):
    """The Shot-based analogue of POST /scenes/{id}/generate — assembles a
    scene's own video from its ready shots instead of one direct Kling call."""
    from app.db import SessionLocal
    from app.models.toon_shot import ToonShot
    from app.services.culturetoon_scene import assemble_scene_from_shots

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        scene = _get_scene_owned(session, scene_id, brand_id, user_id)
        ready_count = session.query(ToonShot).filter_by(scene_id=scene.id, generation_status="ready").count()
        if ready_count < 1:
            raise HTTPException(status_code=400, detail="No ready shots to assemble — generate at least one shot's video first")

        scene.status = "generating"
        scene.generation_error = None
        session.commit()
    finally:
        session.close()

    background_tasks.add_task(assemble_scene_from_shots, user_id=user_id, scene_id=scene_id)
    return {"status": "assembly_started"}

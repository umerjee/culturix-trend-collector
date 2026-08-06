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
}
DEFAULT_ART_STYLE = "cartoon_3d"


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
            f"Character portrait, {style['prompt']}. This must be a fully stylized, illustrated "
            "cartoon character, not a photorealistic photo."
        )
    parts = [grounding, extra, description, "Centered, front-facing, single character, high detail illustration."]
    return " ".join(p for p in parts if p)


def _expand_variant_visual_description(character, variant, raw_description: str) -> str:
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
    provider outage degrades generation quality rather than blocking it."""
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
            return response.choices[0].message.content.strip()
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        message = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception:
        logger.warning("Variant visual-description expansion failed, using raw description", exc_info=True)
        return raw_description


# ── ownership / lookup helpers ───────────────────────────────────────────

def _get_brand_owned(session, brand_id: str, user_id: str):
    from app.models.character_brand import CharacterBrand
    brand = session.query(CharacterBrand).filter_by(id=_uuid.UUID(brand_id)).first()
    if not brand or brand.user_id != _uuid.UUID(user_id):
        raise HTTPException(status_code=404, detail="CultureToons brand not found")
    return brand


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
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
    }


def _serialize_character(c) -> dict:
    return {
        "id": str(c.id), "brand_id": str(c.brand_id), "name": c.name,
        "description": c.description, "base_image_url": c.base_image_url,
        "reference_image_url": c.reference_image_url, "art_style": c.art_style,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _serialize_variant(v) -> dict:
    return {
        "id": str(v.id), "character_id": str(v.character_id), "name": v.name,
        "culture_tag": v.culture_tag, "description": v.description,
        "image_url": v.image_url, "reference_image_url": v.reference_image_url,
        "persona_id": v.persona_id, "is_active": v.is_active,
        "kling_element_id": v.kling_element_id, "kling_element_name": v.kling_element_name,
        "kling_voice_id": v.kling_voice_id, "element_status": v.element_status,
        "element_error": v.element_error,
        "voice_provider": v.voice_provider, "elevenlabs_voice_id": v.elevenlabs_voice_id,
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
        "is_active": bg.is_active,
        "created_at": bg.created_at.isoformat() if bg.created_at else None,
        "updated_at": bg.updated_at.isoformat() if bg.updated_at else None,
    }


def _serialize_script(s) -> dict:
    return {
        "id": str(s.id), "brand_id": str(s.brand_id),
        "character_variant_id": str(s.character_variant_id) if s.character_variant_id else None,
        "character_variant_ids": list(s.character_variant_ids) if s.character_variant_ids else [],
        "source_type": s.source_type, "source_id": s.source_id,
        "hook_line": s.hook_line, "dialogue": s.dialogue, "scene_direction": s.scene_direction,
        "tone": s.tone, "shots": s.shots, "total_duration_seconds": s.total_duration_seconds,
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
        "kling_task_id": t.kling_task_id, "generation_error": t.generation_error,
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
        if "elevenlabs_api_key" in body:
            from app.social.crypto import encrypt
            raw_key = body["elevenlabs_api_key"]
            brand.elevenlabs_api_key_encrypted = encrypt(raw_key) if raw_key else None
        session.commit()
        session.refresh(brand)
        return _serialize_brand(brand)
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
        character = Character(
            brand_id=brand.id, name=body["name"], description=body.get("description"),
            art_style=art_style,
        )
        session.add(character)
        session.commit()
        session.refresh(character)
        return _serialize_character(character)
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
        for field in ("name", "description", "is_active", "art_style"):
            if field in body:
                setattr(character, field, body[field])
        session.commit()
        session.refresh(character)
        return _serialize_character(character)
    finally:
        session.close()


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
        character = _get_character_owned(session, character_id, brand_id, user_id)
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
        character.base_image_url = url
        session.commit()
        session.refresh(character)
        return _serialize_character(character)
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
        variant = CharacterVariant(
            character_id=_uuid.UUID(character_id),
            name=body["name"],
            culture_tag=body.get("culture_tag"),
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
        for field in ("name", "culture_tag", "description", "persona_id", "is_active",
                      "voice_provider", "elevenlabs_voice_id"):
            if field in body:
                setattr(variant, field, body[field])
        session.commit()
        session.refresh(variant)
        return _serialize_variant(variant)
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
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
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
            description = _expand_variant_visual_description(character, variant, raw_description)
            extra += f" Ethnicity / cultural appearance: {variant.culture_tag}."
        elif character.base_image_url:
            # No explicit ethnicity signal — assume family resemblance to
            # the base character is actually wanted (e.g. "grumpier version
            # of the same guy"), keep grounding on their photo.
            reference_image_url = character.base_image_url
            description = _expand_variant_visual_description(character, variant, raw_description)
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
        variant.image_url = url
        session.commit()
        session.refresh(variant)
        return _serialize_variant(variant)
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
        variant = _get_variant_owned(session, variant_id, brand_id, user_id)
        if not variant.image_url:
            raise HTTPException(status_code=400, detail="Variant has no image to register — upload one first")
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
    return {"status": "registration_started"}


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


# ── backgrounds ───────────────────────────────────────────────────────────

@router.post("/backgrounds")
def create_background(body: dict):
    from app.db import SessionLocal
    from app.models.toon_background import ToonBackground
    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id or not body.get("name"):
        raise HTTPException(status_code=400, detail="user_id, brand_id and name are required")
    session = SessionLocal()
    try:
        brand = _get_brand_owned(session, brand_id, user_id)
        background = ToonBackground(
            brand_id=brand.id, name=body["name"], tags=body.get("tags"),
            description=body.get("description"),
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
    session = SessionLocal()
    try:
        background = _get_background_owned(session, background_id, brand_id, user_id)
        for field in ("name", "tags", "description", "is_active"):
            if field in body:
                setattr(background, field, body[field])
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
    num_shots/target_duration_seconds against Kling Omni's real limits
    (MIN_SHOTS/MAX_SHOTS/MIN_TOTAL_SECONDS/MAX_TOTAL_SECONDS in
    culturetoon_script.py) before spending an LLM call — previously an
    out-of-range value only failed later, inside build_kling_prompt, after
    the script was already generated and persisted."""
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
    from app.services.culturetoon_script import generate_toon_script, ToonScriptGenerationError, TONE_OPTIONS as _TONES

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

        try:
            idea = generate_toon_script(
                source, variants, tone=tone,
                num_shots=num_shots,
                target_duration_seconds=target_duration_seconds,
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
        generate_toon_script_from_idea, ToonScriptGenerationError, TONE_OPTIONS as _TONES,
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

        try:
            result = generate_toon_script_from_idea(
                idea, variants, tone=tone,
                num_shots=num_shots,
                target_duration_seconds=target_duration_seconds,
            )
        except ToonScriptGenerationError as exc:
            raise HTTPException(status_code=502, detail=f"Script generation failed: {exc}")

        script = ToonScript(
            brand_id=brand.id,
            character_variant_id=variants[0].id,
            character_variant_ids=[str(v.id) for v in variants],
            source_type="idea",
            hook_line=result.get("hook_line"),
            tone=result.get("tone"),
            shots=result.get("shots"),
            total_duration_seconds=result.get("total_duration_seconds"),
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
        script = _get_script_owned(session, script_id, brand_id, user_id)
        scene = _script_scene_description(script)
        extra_description = (body.get("extra_description") or "").strip()
        description = " ".join(p for p in [scene, extra_description] if p)
        if not description:
            raise HTTPException(
                status_code=400,
                detail="This script has no scene direction or shot actions to generate a background from — "
                       "add one, or pass extra_description.",
            )
        art_style = body.get("art_style") or DEFAULT_ART_STYLE
        if art_style not in ART_STYLES:
            raise HTTPException(status_code=400, detail=f"Unknown art_style: {art_style}")

        prompt = _build_background_prompt(description, art_style)
        from app.media.image_hybrid import HybridImageProvider
        try:
            result = HybridImageProvider().generate(prompt)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Background generation failed: {exc}")

        from app.models.toon_background import ToonBackground
        ext = "jpg" if result.content_type == "image/jpeg" else "png"
        background_id = _uuid.uuid4()
        path = f"culturetoons/{brand_id}/backgrounds/{background_id}.{ext}"
        from app.services.culturetoon_media import save_image, ImageUploadError
        try:
            url = save_image(result.asset_bytes, result.content_type, path)
        except ImageUploadError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to store generated background: {exc}")

        name = (body.get("name") or "").strip() or (script.hook_line or description)[:120]
        background = ToonBackground(
            id=background_id, brand_id=_uuid.UUID(brand_id), name=name,
            image_url=url, description=description,
        )
        session.add(background)
        script.background_id = background_id
        session.commit()
        session.refresh(background)
        return _serialize_background(background)
    finally:
        session.close()


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


@router.post("/toons/{toon_id}/generate-video")
def generate_toon_video(toon_id: str, body: dict, background_tasks: BackgroundTasks):
    """Backgrounded — Kling Omni multi-shot generation is a heavier version
    of exactly the scenario app/shopify/reels.py already solved with
    backgrounding (its Kling call runs up to ~6 min); running this
    synchronously would risk any HTTP gateway timeout in front of it."""
    from app.db import SessionLocal
    from app.services.culturetoon_video import generate_video_for_toon

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")

    session = SessionLocal()
    try:
        toon = _get_toon_owned(session, toon_id, brand_id, user_id)
        from app.models.toon_script import ToonScript
        from app.models.character_variant import CharacterVariant
        script = session.query(ToonScript).filter_by(id=toon.script_id).first()
        variant = session.query(CharacterVariant).filter_by(id=toon.character_variant_id).first()
        if not script or not script.shots:
            raise HTTPException(status_code=400, detail="Toon's script has no shot data — generate/select a shot-structured script first")
        if not variant or variant.element_status != "ready":
            raise HTTPException(status_code=400, detail="Character variant is not a ready Kling element — register it first")

        toon.status = "animating"
        toon.generation_error = None
        session.commit()
    finally:
        session.close()

    background_tasks.add_task(generate_video_for_toon, user_id=user_id, toon_id=toon_id)
    return {"status": "generation_started"}


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

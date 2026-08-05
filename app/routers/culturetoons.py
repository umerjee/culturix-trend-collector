"""CultureToons — Character-Based Posting, the 3rd Culturix product.

Data-management API for a user's character brand: base Characters, their
cultural CharacterVariants, each variant's 10 reusable Expressions,
reusable Backgrounds, punchy skit ToonScripts (optionally trend-tied and/or
AI-suggested), and Toons — the production/posting tracker linking a
variant+script+background into one plannable clip.

Deliberately does NOT generate character art, expressions, backgrounds, or
video — that's a later phase ("once we have built this we will focus on the
tools to use for generating the cartoons"). This is the asset-management
layer: store real Stable-Diffusion-generated PNGs the user uploads, and
track scripts/toons through to posting. Final videos are produced
externally (CapCut/Blender) for now; final_video_url is pasted in manually.
"""
import logging
import uuid as _uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

logger = logging.getLogger("culturix.routers.culturetoons")
router = APIRouter(prefix="/api/culturetoons")

EXPRESSION_NAMES = [
    "Angry", "Confused", "Happy", "Shocked", "Laughing",
    "Side-eye", "Crying", "Annoyed", "Smiling", "Deadpan",
]


# ── ownership / lookup helpers ───────────────────────────────────────────

def _get_brand_for_user(session, user_id: str):
    from app.models.character_brand import CharacterBrand
    brand = session.query(CharacterBrand).filter_by(user_id=_uuid.UUID(user_id)).first()
    if not brand:
        raise HTTPException(status_code=404, detail="No CultureToons brand for this user — create one first")
    return brand


def _get_character_owned(session, character_id: str, user_id: str):
    from app.models.character import Character
    character = session.query(Character).filter_by(id=_uuid.UUID(character_id)).first()
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    brand = _get_brand_for_user(session, user_id)
    if character.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Character not found")
    return character


def _get_variant_owned(session, variant_id: str, user_id: str):
    from app.models.character_variant import CharacterVariant
    variant = session.query(CharacterVariant).filter_by(id=_uuid.UUID(variant_id)).first()
    if not variant:
        raise HTTPException(status_code=404, detail="Character variant not found")
    _get_character_owned(session, str(variant.character_id), user_id)
    return variant


def _get_background_owned(session, background_id: str, user_id: str):
    from app.models.toon_background import ToonBackground
    background = session.query(ToonBackground).filter_by(id=_uuid.UUID(background_id)).first()
    if not background:
        raise HTTPException(status_code=404, detail="Background not found")
    brand = _get_brand_for_user(session, user_id)
    if background.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Background not found")
    return background


def _get_script_owned(session, script_id: str, user_id: str):
    from app.models.toon_script import ToonScript
    script = session.query(ToonScript).filter_by(id=_uuid.UUID(script_id)).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    brand = _get_brand_for_user(session, user_id)
    if script.brand_id != brand.id:
        raise HTTPException(status_code=404, detail="Script not found")
    return script


def _get_toon_owned(session, toon_id: str, user_id: str):
    from app.models.toon import Toon
    toon = session.query(Toon).filter_by(id=_uuid.UUID(toon_id)).first()
    if not toon:
        raise HTTPException(status_code=404, detail="Toon not found")
    brand = _get_brand_for_user(session, user_id)
    if toon.brand_id != brand.id:
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
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
    }


def _serialize_character(c) -> dict:
    return {
        "id": str(c.id), "brand_id": str(c.brand_id), "name": c.name,
        "description": c.description, "base_image_url": c.base_image_url,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _serialize_variant(v) -> dict:
    return {
        "id": str(v.id), "character_id": str(v.character_id), "name": v.name,
        "culture_tag": v.culture_tag, "description": v.description,
        "image_url": v.image_url, "persona_id": v.persona_id, "is_active": v.is_active,
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
        "image_url": bg.image_url, "tags": bg.tags, "is_active": bg.is_active,
        "created_at": bg.created_at.isoformat() if bg.created_at else None,
        "updated_at": bg.updated_at.isoformat() if bg.updated_at else None,
    }


def _serialize_script(s) -> dict:
    return {
        "id": str(s.id), "brand_id": str(s.brand_id),
        "character_variant_id": str(s.character_variant_id) if s.character_variant_id else None,
        "source_type": s.source_type, "source_id": s.source_id,
        "hook_line": s.hook_line, "dialogue": s.dialogue, "scene_direction": s.scene_direction,
        "generation_source": s.generation_source, "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


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
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


# ── brand ─────────────────────────────────────────────────────────────────

@router.post("/brand")
def upsert_brand(body: dict):
    from app.db import SessionLocal
    from app.models.character_brand import CharacterBrand
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    session = SessionLocal()
    try:
        uid = _uuid.UUID(user_id)
        brand = session.query(CharacterBrand).filter_by(user_id=uid).first()
        if brand:
            for field in ("name", "description", "is_active"):
                if field in body:
                    setattr(brand, field, body[field])
        else:
            brand = CharacterBrand(
                user_id=uid,
                name=body.get("name", "My CultureToons Brand"),
                description=body.get("description"),
            )
            session.add(brand)
        session.commit()
        session.refresh(brand)
        return _serialize_brand(brand)
    finally:
        session.close()


@router.get("/brand")
def get_brand(user_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
        return _serialize_brand(brand)
    finally:
        session.close()


# ── characters ────────────────────────────────────────────────────────────

@router.post("/characters")
def create_character(body: dict):
    from app.db import SessionLocal
    from app.models.character import Character
    user_id = body.get("user_id")
    if not user_id or not body.get("name"):
        raise HTTPException(status_code=400, detail="user_id and name are required")
    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
        character = Character(brand_id=brand.id, name=body["name"], description=body.get("description"))
        session.add(character)
        session.commit()
        session.refresh(character)
        return _serialize_character(character)
    finally:
        session.close()


@router.get("/characters")
def list_characters(user_id: str, active_only: bool = True):
    from app.db import SessionLocal
    from app.models.character import Character
    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
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
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    session = SessionLocal()
    try:
        character = _get_character_owned(session, character_id, user_id)
        for field in ("name", "description", "is_active"):
            if field in body:
                setattr(character, field, body[field])
        session.commit()
        session.refresh(character)
        return _serialize_character(character)
    finally:
        session.close()


@router.post("/characters/{character_id}/image")
async def upload_character_image(character_id: str, user_id: str = Form(...), file: UploadFile = File(...)):
    from app.db import SessionLocal
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        character = _get_character_owned(session, character_id, user_id)
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


# ── character variants ───────────────────────────────────────────────────

@router.post("/variants")
def create_variant(body: dict):
    from app.db import SessionLocal
    user_id = body.get("user_id")
    character_id = body.get("character_id")
    if not user_id or not character_id or not body.get("name"):
        raise HTTPException(status_code=400, detail="user_id, character_id and name are required")
    session = SessionLocal()
    try:
        from app.models.character_variant import CharacterVariant
        _get_character_owned(session, character_id, user_id)  # ownership + 404 check
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
def list_variants(user_id: str, character_id: Optional[str] = None, active_only: bool = True):
    from app.db import SessionLocal
    from app.models.character import Character
    from app.models.character_variant import CharacterVariant
    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
        if character_id:
            _get_character_owned(session, character_id, user_id)
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
def get_variant(variant_id: str, user_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, user_id)
        return _serialize_variant(variant)
    finally:
        session.close()


@router.put("/variants/{variant_id}")
def update_variant(variant_id: str, body: dict):
    from app.db import SessionLocal
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, user_id)
        for field in ("name", "culture_tag", "description", "persona_id", "is_active"):
            if field in body:
                setattr(variant, field, body[field])
        session.commit()
        session.refresh(variant)
        return _serialize_variant(variant)
    finally:
        session.close()


@router.post("/variants/{variant_id}/image")
async def upload_variant_image(variant_id: str, user_id: str = Form(...), file: UploadFile = File(...)):
    from app.db import SessionLocal
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, user_id)
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


# ── expressions ───────────────────────────────────────────────────────────

@router.get("/variants/{variant_id}/expressions")
def list_expressions(variant_id: str, user_id: str):
    from app.db import SessionLocal
    from app.models.expression import Expression
    session = SessionLocal()
    try:
        _get_variant_owned(session, variant_id, user_id)
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
async def upload_expression_image(variant_id: str, name: str, user_id: str = Form(...), file: UploadFile = File(...)):
    if name not in EXPRESSION_NAMES:
        raise HTTPException(status_code=400, detail=f"name must be one of {EXPRESSION_NAMES}")
    from app.db import SessionLocal
    from app.models.expression import Expression
    from app.models.character import Character
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        variant = _get_variant_owned(session, variant_id, user_id)
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
def delete_expression(expression_id: str, user_id: str):
    from app.db import SessionLocal
    from app.models.expression import Expression
    session = SessionLocal()
    try:
        expression = session.query(Expression).filter_by(id=_uuid.UUID(expression_id)).first()
        if not expression:
            raise HTTPException(status_code=404, detail="Expression not found")
        _get_variant_owned(session, str(expression.character_variant_id), user_id)  # ownership check
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
    user_id = body.get("user_id")
    if not user_id or not body.get("name"):
        raise HTTPException(status_code=400, detail="user_id and name are required")
    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
        background = ToonBackground(brand_id=brand.id, name=body["name"], tags=body.get("tags"))
        session.add(background)
        session.commit()
        session.refresh(background)
        return _serialize_background(background)
    finally:
        session.close()


@router.get("/backgrounds")
def list_backgrounds(user_id: str, active_only: bool = True):
    from app.db import SessionLocal
    from app.models.toon_background import ToonBackground
    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
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
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    session = SessionLocal()
    try:
        background = _get_background_owned(session, background_id, user_id)
        for field in ("name", "tags", "is_active"):
            if field in body:
                setattr(background, field, body[field])
        session.commit()
        session.refresh(background)
        return _serialize_background(background)
    finally:
        session.close()


@router.post("/backgrounds/{background_id}/image")
async def upload_background_image(background_id: str, user_id: str = Form(...), file: UploadFile = File(...)):
    from app.db import SessionLocal
    from app.services.culturetoon_media import save_image, ImageUploadError
    session = SessionLocal()
    try:
        background = _get_background_owned(session, background_id, user_id)
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
def delete_background(background_id: str, user_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        background = _get_background_owned(session, background_id, user_id)
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
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
        character_variant_id = body.get("character_variant_id")
        if character_variant_id:
            _get_variant_owned(session, character_variant_id, user_id)
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


@router.post("/scripts/suggest")
def suggest_script(body: dict):
    """Synchronous — a single LLM call, matching shopify_generate_product_idea's
    pattern (the caller needs the result immediately to render it)."""
    from app.db import SessionLocal
    from app.models.toon_script import ToonScript
    from app.services.culturetoon_script import generate_toon_script, ToonScriptGenerationError

    user_id = body.get("user_id")
    source_type = body.get("source_type")
    source_id = body.get("source_id")
    character_variant_id = body.get("character_variant_id")

    if not user_id or source_type not in ("persona", "cluster") or source_id is None:
        raise HTTPException(status_code=400, detail="user_id, source_type ('persona'|'cluster') and source_id are required")
    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="source_id must be an integer")

    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
        source = _fetch_trend_source(session, source_type, source_id)
        if not source:
            raise HTTPException(status_code=404, detail=f"{source_type} {source_id} not found")

        variant = None
        if character_variant_id:
            variant = _get_variant_owned(session, character_variant_id, user_id)

        try:
            idea = generate_toon_script(source, variant)
        except ToonScriptGenerationError as exc:
            raise HTTPException(status_code=502, detail=f"Script generation failed: {exc}")

        script = ToonScript(
            brand_id=brand.id,
            character_variant_id=_uuid.UUID(character_variant_id) if character_variant_id else None,
            source_type=source_type,
            source_id=source_id,
            hook_line=idea.get("hook_line"),
            dialogue=idea.get("dialogue"),
            scene_direction=idea.get("scene_direction"),
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
def list_scripts(user_id: str, character_variant_id: Optional[str] = None, status: Optional[str] = None):
    from app.db import SessionLocal
    from app.models.toon_script import ToonScript
    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
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
def get_script(script_id: str, user_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        script = _get_script_owned(session, script_id, user_id)
        return _serialize_script(script)
    finally:
        session.close()


@router.put("/scripts/{script_id}")
def update_script(script_id: str, body: dict):
    from app.db import SessionLocal
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    session = SessionLocal()
    try:
        script = _get_script_owned(session, script_id, user_id)
        for field in ("hook_line", "dialogue", "scene_direction", "status"):
            if field in body:
                setattr(script, field, body[field])
        if "character_variant_id" in body:
            new_variant_id = body["character_variant_id"]
            if new_variant_id:
                _get_variant_owned(session, new_variant_id, user_id)
                script.character_variant_id = _uuid.UUID(new_variant_id)
            else:
                script.character_variant_id = None
        session.commit()
        session.refresh(script)
        return _serialize_script(script)
    finally:
        session.close()


@router.delete("/scripts/{script_id}")
def delete_script(script_id: str, user_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        script = _get_script_owned(session, script_id, user_id)
        script.status = "archived"
        session.commit()
        return {"status": "archived"}
    finally:
        session.close()


# ── toons ─────────────────────────────────────────────────────────────────

@router.post("/toons")
def create_toon(body: dict):
    from app.db import SessionLocal
    from app.models.toon import Toon
    user_id = body.get("user_id")
    character_variant_id = body.get("character_variant_id")
    script_id = body.get("script_id")
    if not user_id or not character_variant_id or not script_id:
        raise HTTPException(status_code=400, detail="user_id, character_variant_id and script_id are required")
    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
        _get_variant_owned(session, character_variant_id, user_id)
        _get_script_owned(session, script_id, user_id)
        background_id = body.get("background_id")
        if background_id:
            _get_background_owned(session, background_id, user_id)

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
def list_toons(user_id: str, status: Optional[str] = None):
    from app.db import SessionLocal
    from app.models.toon import Toon
    session = SessionLocal()
    try:
        brand = _get_brand_for_user(session, user_id)
        query = session.query(Toon).filter_by(brand_id=brand.id)
        if status:
            query = query.filter_by(status=status)
        toons = query.order_by(Toon.created_at.desc()).all()
        return [_serialize_toon(t) for t in toons]
    finally:
        session.close()


@router.get("/toons/{toon_id}")
def get_toon(toon_id: str, user_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        toon = _get_toon_owned(session, toon_id, user_id)
        return _serialize_toon(toon)
    finally:
        session.close()


@router.put("/toons/{toon_id}")
def update_toon(toon_id: str, body: dict):
    from app.db import SessionLocal
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    session = SessionLocal()
    try:
        toon = _get_toon_owned(session, toon_id, user_id)
        if "background_id" in body:
            background_id = body["background_id"]
            if background_id:
                _get_background_owned(session, background_id, user_id)
                toon.background_id = _uuid.UUID(background_id)
            else:
                toon.background_id = None
        for field in ("title", "final_video_url", "status", "platform", "notes"):
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
def delete_toon(toon_id: str, user_id: str):
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        toon = _get_toon_owned(session, toon_id, user_id)
        toon.status = "archived"
        session.commit()
        return {"status": "archived"}
    finally:
        session.close()

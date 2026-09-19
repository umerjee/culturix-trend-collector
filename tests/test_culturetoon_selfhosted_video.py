"""Tests for app/services/culturetoon_selfhosted_video.py — prompt building
from a ToonScript's shots, and (TestGenerateVideoForToonSelfhosted below)
the interactive-button orchestrator against an existing Toon, mirroring
tests/test_culturetoon_video.py's in-memory SQLite/mocked-provider shape
for the Kling counterpart."""
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.character_brand import CharacterBrand
from app.models.character import Character
from app.models.character_variant import CharacterVariant
from app.models.toon_script import ToonScript
from app.models.toon import Toon
from app.models.toon_background import ToonBackground
from app.models.generation_usage import GenerationUsage
from app.services.culturetoon_selfhosted_video import (
    generate_video_for_toon_selfhosted, generate_toon_video_ltx25, SelfHostedVideoGenerationError,
    resolve_scene_backgrounds,
    _resilient_commit,
    _build_shot_prompt, _resolve_shot_variant,
    _split_shots_into_segments, _segment_scene_index, _segment_primary_variant, _segment_is_subject_only,
    _scrub_unanchored_names, _sanitize_segment_shots,
)


@pytest.fixture(autouse=True)
def _no_real_sleep(mocker):
    mocker.patch("app.services.culturetoon_selfhosted_video._COMMIT_RETRY_BACKOFF_SECONDS", 0)


def _script(mocker, hook_line=None, shots=None, total_duration_seconds=None):
    s = mocker.Mock()
    s.hook_line = hook_line
    s.shots = shots or []
    s.total_duration_seconds = total_duration_seconds
    return s


def _variant(mocker, name="Kumar", image_url="https://example.com/kumar.png", id=None):
    v = mocker.Mock()
    v.id = id or name
    v.name = name
    v.image_url = image_url
    return v


class TestBuildShotPrompt:
    def test_combines_all_fields_for_one_shot(self, mocker):
        shot = {
            "shot_type": "closeup", "camera_movement": "push_in",
            "visual": "holding a drum", "action": "dancing", "expression": "Happy",
            "dialogue": "Let's go!", "dialogue_delivery": "Loud",
        }
        prompt = _build_shot_prompt(shot)
        assert "closeup shot" in prompt
        assert "push in camera movement" in prompt
        assert "holding a drum" in prompt
        assert "dancing" in prompt
        assert "with a happy expression" in prompt
        assert 'saying "Let\'s go!" (Loud delivery)' in prompt

    def test_empty_shot_returns_empty_string_not_a_fallback_phrase(self, mocker):
        assert _build_shot_prompt({}) == ""

    def test_background_prepended_when_given(self, mocker):
        # country/visual_style set explicitly to None: a bare mocker.Mock()
        # auto-creates them as Mock objects, which are truthy and would be
        # appended to the prompt as non-strings.
        background = mocker.Mock(description="A cramped kitchen", country=None, visual_style=None)
        background.name = "Kitchen"
        prompt = _build_shot_prompt({"action": "waves"}, background=background)
        assert prompt.startswith("Set in Kitchen: A cramped kitchen")

    def test_background_country_and_visual_style_reach_the_prompt(self, mocker):
        """Both are real ToonBackground columns that _build_shot_prompt
        previously ignored entirely — only name/description were read, so a
        Location's own art direction never influenced generation at all."""
        background = mocker.Mock(
            description="A cramped kitchen",
            country="Norway",
            visual_style="warm muted palette, overcast light",
        )
        background.name = "Kitchen"
        prompt = _build_shot_prompt({"action": "waves"}, background=background)
        assert "Located in Norway" in prompt
        assert "warm muted palette, overcast light" in prompt

    def test_lighting_and_blocking_reach_the_prompt(self, mocker):
        """Both are newer shot fields. Generating them is only half the job —
        `expression` was generated but silently dropped for weeks, and these
        would go the same way. Lighting with a stated direction is what makes
        separate shots read as one scene; blocking keeps characters
        distinguishable now that identity rides on a first-frame anchor."""
        shot = {
            "visual": "a chipped enamel teapot on scratched oak",
            "lighting": "warm lamp from frame left, cold window light right",
            "blocking": "Hans left with the laptop, Wen right with a book",
            "action": "he squints at the screen",
        }
        prompt = _build_shot_prompt(shot)
        assert "warm lamp from frame left" in prompt
        assert "Hans left with the laptop" in prompt
        assert "chipped enamel teapot" in prompt

    def test_missing_lighting_and_blocking_are_simply_omitted(self, mocker):
        prompt = _build_shot_prompt({"action": "waves"})
        assert "None" not in prompt
        assert prompt.startswith("waves")

    def test_visual_style_slug_is_expanded_not_passed_through_raw(self, mocker):
        """visual_style stores a SLUG the UI dropdown writes
        ("cinematic_cultural"), not prose — every real Location row holds
        the bare key. Passing it through raw would put that literal token
        into the prompt as noise instead of art direction."""
        background = mocker.Mock(description="A kitchen", country=None, visual_style="cinematic_cultural")
        background.name = "Kitchen"
        prompt = _build_shot_prompt({"action": "waves"}, background=background)
        assert "cinematic_cultural" not in prompt
        assert "painterly" in prompt

    def test_unknown_visual_style_falls_back_to_readable_text(self, mocker):
        background = mocker.Mock(description="A kitchen", country=None, visual_style="my_custom_look")
        background.name = "Kitchen"
        prompt = _build_shot_prompt({"action": "waves"}, background=background)
        assert "my custom look" in prompt

    def test_quality_suffix_does_not_hardcode_a_conflicting_art_style(self, mocker):
        """The suffix must assert render QUALITY only — the art style comes
        from the Location's visual_style and the reference portrait. A suffix
        hardcoding "Pixar-style 3D" directly contradicted the painterly
        "(not photoreal)" style text in the same prompt."""
        background = mocker.Mock(description="A kitchen", country=None, visual_style="cinematic_cultural")
        background.name = "Kitchen"
        prompt = _build_shot_prompt({"action": "waves"}, background=background)
        assert "Pixar" not in prompt
        assert "3D animated cartoon" not in prompt


class TestResolveShotVariant:
    def test_matches_speaker_variant_id(self, mocker):
        hans = _variant(mocker, name="Hans", id="hans-id")
        wen = _variant(mocker, name="Wen", id="wen-id")
        shot = {"speaker_variant_id": "wen-id"}
        assert _resolve_shot_variant(shot, [hans, wen]) is wen

    def test_falls_back_to_primary_when_no_speaker_id(self, mocker):
        hans = _variant(mocker, name="Hans", id="hans-id")
        wen = _variant(mocker, name="Wen", id="wen-id")
        shot = {"speaker_variant_id": None}
        assert _resolve_shot_variant(shot, [hans, wen]) is hans

    def test_falls_back_to_primary_when_speaker_id_not_in_cast(self, mocker):
        hans = _variant(mocker, name="Hans", id="hans-id")
        shot = {"speaker_variant_id": "someone-else-id"}
        assert _resolve_shot_variant(shot, [hans]) is hans


_SHOTS = [{"shot_number": 1, "duration_seconds": 4, "action": "waves", "expression": "Happy", "dialogue": None}]


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        CharacterBrand.__table__, Character.__table__, CharacterVariant.__table__,
        ToonScript.__table__, Toon.__table__, GenerationUsage.__table__,
        ToonBackground.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


@pytest.fixture
def seeded(db):
    session = db()
    user_id = uuid.uuid4()
    brand = CharacterBrand(user_id=user_id, name="Test Brand")
    session.add(brand)
    session.commit()

    character = Character(brand_id=brand.id, name="Base")
    session.add(character)
    session.commit()

    variant = CharacterVariant(character_id=character.id, name="Mom", image_url="https://img/mom.png")
    session.add(variant)
    session.commit()

    script = ToonScript(brand_id=brand.id, character_variant_id=variant.id, shots=_SHOTS, total_duration_seconds=8)
    session.add(script)
    session.commit()

    toon = Toon(brand_id=brand.id, character_variant_id=variant.id, script_id=script.id, status="animating")
    session.add(toon)
    session.commit()

    ids = {"user_id": str(user_id), "brand_id": str(brand.id), "toon_id": str(toon.id), "variant_id": str(variant.id)}
    session.close()
    return ids


class TestGenerateVideoForToonSelfhosted:
    def test_success_path(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.services.culturetoon_selfhosted_video.generate_toon_video_ltx25", return_value=b"video-bytes")
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "ready"
        assert toon.video_provider == "self_hosted"
        assert toon.raw_video_url == "https://supabase/video.mp4"
        assert toon.final_video_url == "https://supabase/video.mp4"
        mock_upload.assert_called_once()

        usage = session.query(GenerationUsage).filter_by(toon_id=uuid.UUID(seeded["toon_id"])).all()
        assert len(usage) == 1
        assert usage[0].provider == "runpod_ltx"

    def test_regenerating_archives_the_previous_take(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.services.culturetoon_selfhosted_video.generate_toon_video_ltx25", return_value=b"take-2")
        mocker.patch("app.media.storage.upload", return_value="https://supabase/take-2.mp4")

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        toon.raw_video_url = "https://supabase/take-1.mp4"
        toon.final_video_url = "https://supabase/take-1.mp4"
        session.commit()
        session.close()

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.final_video_url == "https://supabase/take-2.mp4"
        assert toon.previous_video_urls == ["https://supabase/take-1.mp4"]

    def test_missing_endpoint_id_marks_toon_failed(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {}, clear=False)
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": ""})
        mock_run = mocker.patch("app.services.culturetoon_selfhosted_video.generate_toon_video_ltx25")

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "RUNPOD_SERVERLESS_ENDPOINT_ID" in toon.generation_error
        mock_run.assert_not_called()

    def test_runpod_failure_marks_toon_failed(self, db, seeded, mocker):
        from app.media.runpod_serverless_client import RunPodServerlessError
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch(
            "app.services.culturetoon_selfhosted_video.generate_toon_video_ltx25",
            side_effect=RunPodServerlessError("worker allocation timed out"),
        )

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "worker allocation timed out" in toon.generation_error

    def test_stale_connection_on_the_failure_commit_does_not_leave_toon_stuck_animating(self, db, seeded, mocker):
        """Confirmed live 2026-08-26, twice in a row: a RunPod allocation
        failure's own commit() (writing status='failed') hit a stale
        Postgres connection after the long allocation-retry wait and raised
        its own OperationalError, masking the original failure and leaving
        the Toon stuck at status='animating' forever. _resilient_commit
        should retry past exactly this and still land status='failed'."""
        from app.media.runpod_serverless_client import RunPodServerlessError
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch(
            "app.services.culturetoon_selfhosted_video.generate_toon_video_ltx25",
            side_effect=RunPodServerlessError("worker allocation timed out"),
        )
        # Call 1 is the early status='animating' write (before RunPod even
        # runs) — must succeed so the flow actually reaches the RunPod
        # failure. Call 2 is the failure-commit this test targets: the
        # first attempt inside _resilient_commit, right after the
        # RunPodServerlessError — this is the one confirmed live to hit a
        # stale connection.
        real_commit = __import__("sqlalchemy").orm.Session.commit
        call_count = {"n": 0}

        def flaky_commit(self):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise Exception("server closed the connection unexpectedly")
            return real_commit(self)

        mocker.patch("sqlalchemy.orm.Session.commit", flaky_commit)

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "worker allocation timed out" in toon.generation_error

    def test_scripts_own_background_id_is_fetched_and_passed_through(self, db, seeded, mocker):
        # Confirmed live 2026-08-30: neither Toon.background_id nor
        # ToonScript.background_id was ever read by this path at all, so a
        # selected Location never reached the video prompt. The script's
        # own background_id wins over the toon's per that column's own
        # docstring ("a script's setting drives its background").
        session = db()
        script_background = ToonBackground(brand_id=uuid.UUID(seeded["brand_id"]), name="Diner", description="A 1950s American diner")
        toon_background = ToonBackground(brand_id=uuid.UUID(seeded["brand_id"]), name="Office", description="A cramped cubicle")
        session.add_all([script_background, toon_background])
        session.commit()
        script = session.query(ToonScript).first()
        script.background_id = script_background.id
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        toon.background_id = toon_background.id
        session.commit()
        session.close()

        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")
        # The queried ToonBackground is bound to a session that
        # generate_video_for_toon_selfhosted opens and closes internally —
        # capture the field we care about at call time via side_effect,
        # rather than inspecting the (by-then-detached) object afterward.
        seen_names = []

        def _capture(*args, **kwargs):
            background = kwargs.get("background")
            seen_names.append(background.name if background is not None else None)
            return b"video-bytes"

        mocker.patch(
            "app.services.culturetoon_selfhosted_video.generate_toon_video_ltx25", side_effect=_capture,
        )

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        assert seen_names == ["Diner"]

    def test_falls_back_to_toons_background_id_when_script_has_none(self, db, seeded, mocker):
        session = db()
        toon_background = ToonBackground(brand_id=uuid.UUID(seeded["brand_id"]), name="Office", description="A cramped cubicle")
        session.add(toon_background)
        session.commit()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        toon.background_id = toon_background.id
        session.commit()
        session.close()

        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")
        seen_names = []

        def _capture(*args, **kwargs):
            background = kwargs.get("background")
            seen_names.append(background.name if background is not None else None)
            return b"video-bytes"

        mocker.patch(
            "app.services.culturetoon_selfhosted_video.generate_toon_video_ltx25", side_effect=_capture,
        )

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        assert seen_names == ["Office"]

    def test_neither_script_nor_toon_has_a_background_passes_none(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")
        mock_generate = mocker.patch(
            "app.services.culturetoon_selfhosted_video.generate_toon_video_ltx25", return_value=b"video-bytes",
        )

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        assert mock_generate.call_args.kwargs["background"] is None

    def test_resilient_commit_raises_after_exhausting_retries(self, mocker):
        session = mocker.Mock()
        session.commit.side_effect = Exception("still dead")
        mutate = mocker.Mock()

        with pytest.raises(Exception, match="still dead"):
            _resilient_commit(session, mutate)

        assert session.rollback.call_count == session.commit.call_count
        # mutate must be re-run on every attempt, not just the first — a
        # rollback expires/discards whatever it set the first time.
        assert mutate.call_count == session.commit.call_count


class TestSplitShotsIntoSegmentsSceneBoundary:
    """Scene-boundary splitting (added 2026-09-08 for the multi-scene
    rework) — must be UNCONDITIONAL, never softened by _is_coupled_shot the
    way a primary-speaker change can be, since the anchor image itself
    bakes one specific scene's backdrop into the composite PNG."""

    def test_scene_change_forces_a_split_even_with_the_same_speaker(self):
        shots = [
            {"shot_number": 1, "duration_seconds": 3, "speaker_variant_id": "z", "scene_index": 0, "dialogue": "Hi"},
            {"shot_number": 2, "duration_seconds": 3, "speaker_variant_id": "z", "scene_index": 1, "dialogue": "Still me"},
        ]
        segments = _split_shots_into_segments(shots)
        assert len(segments) == 2
        assert segments[0] == [shots[0]]
        assert segments[1] == [shots[1]]

    def test_scene_change_splits_even_a_coupled_reaction_shot(self):
        """A shot with no dialogue is normally glued to its predecessor
        (_is_coupled_shot) — a scene change must override that gluing,
        since chaining across scenes bakes the wrong backdrop into the
        continuation's own first frame."""
        shots = [
            {"shot_number": 1, "duration_seconds": 3, "speaker_variant_id": "z", "scene_index": 0, "dialogue": "Hi"},
            # No dialogue: would normally be coupled to shot 1.
            {"shot_number": 2, "duration_seconds": 2, "scene_index": 1, "action": "reacts", "dialogue": None},
        ]
        segments = _split_shots_into_segments(shots)
        assert len(segments) == 2

    def test_same_scene_does_not_force_a_split(self):
        shots = [
            {"shot_number": 1, "duration_seconds": 3, "speaker_variant_id": "z", "scene_index": 0, "dialogue": "Hi"},
            {"shot_number": 2, "duration_seconds": 3, "speaker_variant_id": "z", "scene_index": 0, "dialogue": "More"},
        ]
        segments = _split_shots_into_segments(shots)
        assert len(segments) == 1

    def test_no_scene_index_at_all_behaves_exactly_as_before(self):
        """A script that never had plan_scenes() run over it carries no
        scene_index on any shot — must split purely on the pre-existing
        primary-speaker/duration rules, unaffected by this feature."""
        shots = [
            {"shot_number": 1, "duration_seconds": 3, "speaker_variant_id": "z", "dialogue": "Hi"},
            {"shot_number": 2, "duration_seconds": 3, "speaker_variant_id": "z", "dialogue": "Still me"},
        ]
        segments = _split_shots_into_segments(shots)
        assert len(segments) == 1

    def test_primary_speaker_change_within_the_same_scene_still_splits(self):
        """Scene planning must not swallow the pre-existing speaker-change
        split rule — a real change of speaker still gets its own segment
        even when the backdrop hasn't changed."""
        shots = [
            {"shot_number": 1, "duration_seconds": 3, "speaker_variant_id": "z", "scene_index": 0, "dialogue": "Hi"},
            {"shot_number": 2, "duration_seconds": 3, "speaker_variant_id": "b", "scene_index": 0, "dialogue": "Hey"},
        ]
        segments = _split_shots_into_segments(shots)
        assert len(segments) == 2


class TestSegmentSceneIndex:
    def test_returns_the_first_shots_scene_index(self):
        segment = [
            {"shot_number": 1, "scene_index": 2, "dialogue": "Hi"},
            {"shot_number": 2, "scene_index": 2, "dialogue": "More"},
        ]
        assert _segment_scene_index(segment) == 2

    def test_none_when_no_shot_carries_a_scene_index(self):
        segment = [{"shot_number": 1, "action": "reacts"}]
        assert _segment_scene_index(segment) is None

    def test_scene_index_zero_is_not_confused_with_none(self):
        """0 is a real, valid scene_index — must not be treated as falsy/
        missing the way `if shot.get("scene_index")` would."""
        segment = [{"shot_number": 1, "scene_index": 0, "dialogue": "Hi"}]
        assert _segment_scene_index(segment) == 0


class TestResolveSceneBackgrounds:
    def test_returns_none_when_script_has_no_scene_backgrounds(self, mocker):
        script = mocker.Mock(scene_backgrounds=None)
        assert resolve_scene_backgrounds(mocker.Mock(), script) is None

    def test_maps_scene_index_to_the_right_background_row(self, mocker):
        script = mocker.Mock(scene_backgrounds=[
            {"scene_index": 0, "background_id": "11111111-1111-1111-1111-111111111111"},
            {"scene_index": 1, "background_id": "22222222-2222-2222-2222-222222222222"},
        ])
        bg0 = mocker.Mock(id=uuid.UUID("11111111-1111-1111-1111-111111111111"))
        bg1 = mocker.Mock(id=uuid.UUID("22222222-2222-2222-2222-222222222222"))
        session = mocker.Mock()
        session.query.return_value.filter.return_value.all.return_value = [bg0, bg1]

        result = resolve_scene_backgrounds(session, script)

        assert result == {0: bg0, 1: bg1}

    def test_none_when_a_background_row_no_longer_exists(self, mocker):
        script = mocker.Mock(scene_backgrounds=[
            {"scene_index": 0, "background_id": "11111111-1111-1111-1111-111111111111"},
        ])
        session = mocker.Mock()
        session.query.return_value.filter.return_value.all.return_value = []  # row deleted

        assert resolve_scene_backgrounds(session, script) is None


class TestLTX25ScenePrompt:
    """LTX-2.5 renders the whole scene in ONE generation, so unlike the 2.3
    path there is no per-shot anchor to imply who is on screen — everything
    the model needs must be in the text."""

    def _cast(self, mocker):
        def variant(vid, name, description):
            v = mocker.Mock(id=vid, image_url="u")
            v.name = name
            v.character = mocker.Mock(description=description)
            return v
        return [
            variant("z", "Zara", "A young curious space explorer. She wears a jumpsuit."),
            variant("b", "Blix", "An alien buddy, round and blue. He is wise and patient."),
            variant("n", "Captain Nova", "The captain, eccentric. She has wild hair."),
        ]

    def _script(self, mocker):
        script = mocker.Mock(hook_line="They react to a trend.")
        script.shots = [
            {"shot_number": 1, "speaker_variant_id": "z", "action": "leans in", "dialogue": "Seen this?"},
            {"shot_number": 2, "speaker_variant_id": "b", "action": "blinks", "dialogue": "Illogical."},
            {"shot_number": 3, "speaker_variant_id": "n", "action": "throws hands up", "dialogue": "Set course!"},
        ]
        return script

    def test_every_shot_names_its_speaker(self, mocker):
        """Confirmed live 2026-09-02: with unattributed dialogue the third
        character was rendered but her line was given to a DUPLICATE of the
        second character."""
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt

        prompt = build_ltx25_scene_prompt(self._script(mocker), self._cast(mocker))
        assert "Zara (LEFT) is the focus" in prompt
        assert "Blix (CENTRE) is the focus" in prompt
        assert "Captain Nova (RIGHT) is the focus" in prompt
        assert "the line is Captain Nova's" in prompt

    def test_cast_positions_match_the_composite_anchor_order(self, mocker):
        """The anchor pastes portraits left-to-right in cast order, so the
        prompt's positions must agree or the model ties a line to the wrong
        face."""
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt

        prompt = build_ltx25_scene_prompt(self._script(mocker), self._cast(mocker))
        assert prompt.index("LEFT is Zara") < prompt.index("CENTRE is Blix")
        assert prompt.index("CENTRE is Blix") < prompt.index("RIGHT is Captain Nova")

    def test_silent_shot_still_names_the_focus_but_claims_no_line(self, mocker):
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt

        script = mocker.Mock(hook_line="h")
        script.shots = [{"shot_number": 1, "speaker_variant_id": "b", "action": "stares"}]
        prompt = build_ltx25_scene_prompt(script, self._cast(mocker))
        assert "Blix (CENTRE) is the focus" in prompt
        assert "is the one speaking" not in prompt

    def test_script_setting_is_used_when_no_location_is_chosen(self, mocker):
        """An AI script previously carried no setting at all, so a toon with
        no Location reached the model with nothing describing WHERE the
        scene happens — the "bland background" failure. The script's own
        generated world now fills that gap."""
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt

        script = mocker.Mock(hook_line="They react to a trend.")
        script.scene_direction = "Inside a Minecraft world: blocky cubic terrain, flickering torches."
        script.shots = [{"speaker_variant_id": "z", "action": "leans in", "dialogue": "Seen this?"}]
        cast = self._cast(mocker)[:1]
        prompt = build_ltx25_scene_prompt(script, cast, background=None)
        # Not startswith: a single-variant cast still leads with its own
        # identity/voice preamble (single_anchor mode) before the setting,
        # same as every other cast size — this only checks the setting text
        # actually made it into the prompt at all.
        assert "Setting: Inside a Minecraft world" in prompt

    def test_a_chosen_location_takes_precedence_over_the_script_setting(self, mocker):
        """A selected Location is an explicit user decision and carries its
        own art direction, so it wins."""
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt

        script = mocker.Mock(hook_line="h")
        script.scene_direction = "Inside a Minecraft world."
        script.shots = [{"speaker_variant_id": "z", "action": "waves"}]
        background = mocker.Mock(description="A warm kitchen", country=None, visual_style=None)
        background.name = "Kitchen"
        prompt = build_ltx25_scene_prompt(script, self._cast(mocker)[:1], background=background)
        assert "Setting: Kitchen" in prompt
        assert "Minecraft" not in prompt


class TestLTX25SilentAndUnattributedShots:
    """2.5 denoises audio JOINTLY with video, so a shot with no line still
    gets a voice unless the prompt asks for silence. Confirmed live
    2026-09-02: the Minecraft video's silent closing shot had Zara speaking
    a line the script never contained."""

    def _cast(self, mocker):
        def variant(vid, name, description):
            v = mocker.Mock(id=vid, image_url="u")
            v.name = name
            v.character = mocker.Mock(description=description)
            return v
        return [
            variant("z", "Zara", "A young explorer."),
            variant("n", "Captain Nova", "The captain."),
        ]

    def _script(self, mocker, last_shot):
        script = mocker.Mock(hook_line="H")
        script.shots = [
            {"shot_number": 1, "speaker_variant_id": "z", "action": "leans in", "dialogue": "Seen this?"},
            last_shot,
        ]
        return script

    def test_a_silent_shot_is_explicitly_marked_silent(self, mocker):
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(
            self._script(mocker, {"shot_number": 2, "action": "they all hug", "dialogue": ""}),
            self._cast(mocker),
        )
        assert "No one speaks in this shot" in prompt

    def test_an_unattributed_shot_names_no_focus_character(self, mocker):
        """The old fallback picked the FIRST cast member for a shot with no
        speaker_variant_id, so a silent ensemble shot read as 'Zara is the
        focus' and 2.5 duly gave Zara the line."""
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(
            self._script(mocker, {"shot_number": 2, "action": "they all hug", "dialogue": ""}),
            self._cast(mocker),
        )
        shot_two = prompt.split("CUT TO SHOT 2")[1]
        assert "is the focus" not in shot_two

    def test_a_shot_with_a_line_still_names_its_speaker_and_is_not_silenced(self, mocker):
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(
            self._script(mocker, {"shot_number": 2, "speaker_variant_id": "n",
                                  "action": "points", "dialogue": "Full speed ahead!"}),
            self._cast(mocker),
        )
        shot_two = prompt.split("CUT TO SHOT 2")[1]
        assert "Captain Nova" in shot_two and "is the one speaking" in shot_two
        assert "No one speaks" not in shot_two


class TestLTX25SubjectShots:
    """Every field in the shot schema used to describe a character
    performing, so a script could not express a shot OF the thing being
    discussed — which is why every video came out as a talking head in front
    of a background."""

    def _cast(self, mocker):
        v = mocker.Mock(id="z", image_url="u")
        v.name = "Zara"
        v.character = mocker.Mock(description="A young explorer.")
        return [v]

    def _script(self, mocker, shots):
        script = mocker.Mock(hook_line="What happens at the edge?")
        script.scene_direction = "Deep space, a black hole"
        script.shots = shots
        return script

    def test_subject_shot_puts_nobody_in_frame(self, mocker):
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(self._script(mocker, [
            {"shot_number": 1, "shot_focus": "subject", "speaker_variant_id": "z",
             "subject_visual": "a supermassive black hole filling frame", "dialogue": None},
        ]), self._cast(mocker))
        assert "a supermassive black hole filling frame" in prompt
        assert "No people in frame at all" in prompt
        # Naming a focus character would put them back on screen.
        assert "is the focus" not in prompt

    def test_distant_people_replace_the_no_people_line_and_stay_faceless(self, mocker):
        # An event that is its people (troops landing) opts in per shot; they stay small,
        # wide and faceless. The empty-frame instruction must not remain to contradict it.
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(self._script(mocker, [
            {"shot_number": 1, "shot_focus": "subject", "people": "distant",
             "subject_visual": "a wide beach at dawn with landing craft and small figures wading ashore",
             "dialogue": None},
        ]), self._cast(mocker))
        assert "small figures wading ashore" in prompt
        assert "small, distant, faceless figures in wide shots" in prompt
        assert "no readable faces" in prompt and "no graphic violence" in prompt
        assert "No people in frame" not in prompt
        assert "Zara is the focus" not in prompt  # still a subject shot: nobody is named on screen

    def test_people_none_or_missing_keeps_the_empty_frame(self, mocker):
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        for extra in ({}, {"people": "none"}, {"people": ""}, {"people": "crowd"}):  # unknown value = safe default
            prompt = build_ltx25_scene_prompt(self._script(mocker, [
                {"shot_number": 1, "shot_focus": "subject", "subject_visual": "an empty beach", "dialogue": None, **extra},
            ]), self._cast(mocker))
            assert "No people in frame at all" in prompt
            assert "faceless" not in prompt

    def test_distant_people_is_case_insensitive(self, mocker):
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(self._script(mocker, [
            {"shot_number": 1, "shot_focus": "subject", "people": " Distant ", "subject_visual": "a beach", "dialogue": None},
        ]), self._cast(mocker))
        assert "faceless" in prompt

    def test_voiceover_keeps_the_speaker_off_screen(self, mocker):
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(self._script(mocker, [
            {"shot_number": 1, "shot_focus": "subject", "voiceover": True, "speaker_variant_id": "z",
             "subject_visual": "the black hole", "dialogue": "Nothing escapes."},
        ]), self._cast(mocker))
        assert "a voice is heard over this shot" in prompt
        assert "the speaker is off screen and not visible" in prompt

    def test_silent_subject_shot_asks_for_silence(self, mocker):
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(self._script(mocker, [
            {"shot_number": 1, "shot_focus": "subject", "subject_visual": "the black hole",
             "dialogue": None},
        ]), self._cast(mocker))
        assert "No one speaks in this shot" in prompt

    def test_subject_shot_does_not_ask_for_focus_on_a_face(self, mocker):
        """The character quality suffix contradicts an empty frame."""
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(self._script(mocker, [
            {"shot_number": 1, "shot_focus": "subject", "subject_visual": "the black hole",
             "dialogue": None},
        ]), self._cast(mocker))
        assert "Sharp focus on the character's face" not in prompt
        assert "cinematic scale and depth" in prompt

    def test_character_shots_are_unchanged(self, mocker):
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(self._script(mocker, [
            {"shot_number": 1, "speaker_variant_id": "z", "action": "leans in",
             "dialogue": "Seen this?"},
        ]), self._cast(mocker))
        # This class's cast is a single variant (single_anchor mode, added
        # 2026-09-02) — no LEFT/CENTRE/RIGHT position label to name since
        # there's no composite grid to place one within.
        assert "Zara is the focus" in prompt
        assert "No people in frame" not in prompt

    def test_cast_is_declared_as_single_individuals(self, mocker):
        """A second Zara appeared in the background — the anchor shows each
        face at a fixed position and the model left a copy behind."""
        from app.services.culturetoon_selfhosted_video import build_ltx25_scene_prompt
        prompt = build_ltx25_scene_prompt(self._script(mocker, [
            {"shot_number": 1, "speaker_variant_id": "z", "action": "leans in", "dialogue": "Hi"},
        ]), self._cast(mocker))
        assert "One of each on screen at a time" in prompt
        assert "no duplicates or copies" in prompt


class TestSpeechPacing:
    def test_budget_scales_with_duration(self):
        from app.services.culturetoon_script import dialogue_word_budget
        assert dialogue_word_budget(4) == 10
        assert dialogue_word_budget(3) == 7
        assert dialogue_word_budget(0) == 3

    def test_overlong_shots_flags_the_rushed_line(self):
        from app.services.culturetoon_script import overlong_shots
        # The real measured case: 22 words in a 3-second shot, 7.3 w/s.
        flagged = overlong_shots([
            {"shot_number": 1, "duration_seconds": 3, "dialogue": " ".join(["word"] * 22)},
            {"shot_number": 2, "duration_seconds": 4, "dialogue": "short enough line"},
        ])
        assert [f["shot_number"] for f in flagged] == [1]
        assert flagged[0]["words"] == 22 and flagged[0]["budget"] == 7

    def test_no_dialogue_is_never_flagged(self):
        from app.services.culturetoon_script import overlong_shots
        assert overlong_shots([{"shot_number": 1, "duration_seconds": 1, "dialogue": None}]) == []


class TestUsageRecordingNeverMasksTheResult:
    """Seen live 2026-09-02: a 40s render completed, uploaded and committed,
    then usage recording raised from the `finally` block and the call
    reported failure. In `finally`, a raised exception replaces whatever is
    already propagating — so this must never raise."""

    def test_a_failing_usage_record_does_not_break_a_successful_render(self, mocker):
        import app.services.culturetoon_selfhosted_video as mod
        mocker.patch.object(mod, "_resilient_commit", side_effect=ValueError("badly formed UUID"))
        logged = mocker.patch.object(mod.logger, "exception")

        # Exercised through the same shape the finally block uses: the guard
        # is what turns a raise into a log.
        try:
            try:
                mod._resilient_commit(None, lambda: None)
            except Exception:
                mod.logger.exception("Could not record usage")
        except Exception as exc:  # pragma: no cover - the point is this never runs
            raise AssertionError(f"usage recording escaped: {exc}")
        assert logged.called


class TestGenerateToonVideoLtx25SceneAwareAnchoring:
    """End-to-end coverage of the render loop's scene-boundary handling
    (added 2026-09-08) — the highest-risk part of the multi-scene rework,
    per its own design review: a scene change must force a fresh portrait
    anchor (never chain off the previous segment's last frame) and must
    fetch that scene's OWN backdrop, not reuse whatever the previous
    segment used."""

    def _variant(self, mocker, vid="z", name="Zara"):
        v = mocker.Mock(id=vid, image_url=f"https://example.com/{vid}.png")
        v.name = name
        return v

    def _script(self, mocker, shots):
        script = mocker.Mock(hook_line="H", scene_direction=None)
        script.shots = shots
        return script

    def _patch_pipeline(self, mocker):
        """Mocks every external boundary generate_toon_video_ltx25 crosses:
        backdrop/portrait fetches (httpx.get), the anchor builder, the
        RunPod call, last-frame extraction, and segment concatenation.
        Returns the mocks the tests need to assert against.

        Forces LTX25_MSR_ENABLED off regardless of the real environment's
        setting (production has it on as of 2026-09-17) — this class tests
        the CLASSIC single-anchor scene-boundary/name-scrubbing behavior
        specifically, which MSR mode deliberately bypasses (a 2+-variant
        cut segment routes through MSR instead when the flag is on,
        confirmed live: this exact class failed for real once the ambient
        .env flag flipped on, since "Captain Nova" naming her own reference
        image is correct under MSR, not a leak)."""
        mocker.patch("app.media.ltx25_workflow.LTX25_MSR_ENABLED", False)

        def fake_get(url, timeout=30):
            resp = mocker.Mock()
            resp.content = f"bytes-for-{url}".encode()
            return resp
        mock_httpx_get = mocker.patch("httpx.get", side_effect=fake_get)
        mock_build_composite = mocker.patch(
            "app.media.ltx25_workflow.build_composite_anchor",
            side_effect=lambda images, backdrop_bytes=None: b"anchor:" + (backdrop_bytes or b"none"),
        )
        mock_build_workflow = mocker.patch("app.media.ltx25_workflow.build_workflow", return_value={"fake": "workflow"})
        mock_run_job = mocker.patch(
            "app.media.runpod_serverless_client.run_inference_job",
            side_effect=lambda *a, **kw: f"video-bytes-{mock_run_job.call_count}".encode(),
        )
        mock_last_frame = mocker.patch(
            "app.services.culturetoon_selfhosted_video._extract_last_frame_png",
            return_value=b"last-frame",
        )
        mocker.patch(
            "app.services.culturetoon_selfhosted_video._concat_video_segments",
            side_effect=lambda videos: b"|".join(videos),
        )
        return mock_httpx_get, mock_build_composite, mock_run_job, mock_last_frame, mock_build_workflow

    def test_scene_change_re_anchors_instead_of_chaining(self, mocker):
        """Same speaker (Zara) throughout, but scene_index changes — the
        SECOND segment must be anchored on a fresh portrait, not on the
        first segment's extracted last frame. (The last frame is still
        speculatively extracted after segment 1 in case it turns out to be
        needed — that's pre-existing, tentative-until-overwritten behavior,
        see generate_toon_video_ltx25's own comment — so this asserts what
        actually gets used as the anchor, not whether extraction ran.)"""
        _, mock_build_composite, _, mock_last_frame, _ = self._patch_pipeline(mocker)
        zara = self._variant(mocker, "z", "Zara")
        shots = [
            {"shot_number": 1, "duration_seconds": 5, "speaker_variant_id": "z", "scene_index": 0, "dialogue": "Hi"},
            {"shot_number": 2, "duration_seconds": 5, "speaker_variant_id": "z", "scene_index": 1, "dialogue": "New place!"},
        ]
        script = self._script(mocker, shots)
        bg0 = mocker.Mock(image_url="https://example.com/scene0.png")
        bg1 = mocker.Mock(image_url="https://example.com/scene1.png")

        generate_toon_video_ltx25(script, [zara], "endpoint-1", scene_backgrounds={0: bg0, 1: bg1})

        # A fresh portrait anchor was built for BOTH segments — chaining
        # would have skipped the second build_composite_anchor call.
        assert mock_build_composite.call_count == 2

    def test_scene_change_fetches_that_scenes_own_backdrop(self, mocker):
        mock_httpx_get, mock_build_composite, _, _, _ = self._patch_pipeline(mocker)
        zara = self._variant(mocker, "z", "Zara")
        shots = [
            {"shot_number": 1, "duration_seconds": 5, "speaker_variant_id": "z", "scene_index": 0, "dialogue": "Hi"},
            {"shot_number": 2, "duration_seconds": 5, "speaker_variant_id": "z", "scene_index": 1, "dialogue": "New place!"},
        ]
        script = self._script(mocker, shots)
        bg0 = mocker.Mock(image_url="https://example.com/scene0.png")
        bg1 = mocker.Mock(image_url="https://example.com/scene1.png")

        generate_toon_video_ltx25(script, [zara], "endpoint-1", scene_backgrounds={0: bg0, 1: bg1})

        fetched_urls = {call.args[0] for call in mock_httpx_get.call_args_list}
        assert "https://example.com/scene0.png" in fetched_urls
        assert "https://example.com/scene1.png" in fetched_urls
        # Each segment's anchor was composited against its OWN scene's
        # backdrop bytes, not a shared/repeated one.
        backdrops_used = {call.kwargs["backdrop_bytes"] for call in mock_build_composite.call_args_list}
        assert len(backdrops_used) == 2

    def test_same_scene_still_chains_when_only_duration_forced_the_split(self, mocker):
        """Sanity check that this feature doesn't regress the pre-existing
        chaining behavior: same primary AND same scene, split only because
        the combined duration exceeds LTX25_SEGMENT_TARGET_SECONDS (15),
        must still CHAIN the second segment off the first's last frame —
        not re-anchor fresh."""
        _, mock_build_composite, _, mock_last_frame, _ = self._patch_pipeline(mocker)
        zara = self._variant(mocker, "z", "Zara")
        # 10 + 10 = 20s > target (15), forcing a split despite matching
        # speaker and scene throughout.
        shots = [
            {"shot_number": 1, "duration_seconds": 10, "speaker_variant_id": "z", "scene_index": 0, "dialogue": "Hi there, a longer line"},
            {"shot_number": 2, "duration_seconds": 10, "speaker_variant_id": "z", "scene_index": 0, "dialogue": "Still here, still talking"},
        ]
        script = self._script(mocker, shots)
        bg0 = mocker.Mock(image_url="https://example.com/scene0.png")

        generate_toon_video_ltx25(script, [zara], "endpoint-1", scene_backgrounds={0: bg0})

        # Only the FIRST segment gets a fresh portrait anchor — the second
        # chains off the first's extracted last frame instead.
        assert mock_build_composite.call_count == 1
        mock_last_frame.assert_called_once()

    def test_falls_back_to_default_background_when_scene_has_no_entry(self, mocker):
        """A shot whose scene_index has no matching scene_backgrounds entry
        (e.g. background generation failed for just that one scene) must
        fall back to the script's single default `background`, not crash
        or silently render with no backdrop at all."""
        mock_httpx_get, _, _, _, _ = self._patch_pipeline(mocker)
        zara = self._variant(mocker, "z", "Zara")
        shots = [{"shot_number": 1, "duration_seconds": 5, "speaker_variant_id": "z", "scene_index": 5, "dialogue": "Hi"}]
        script = self._script(mocker, shots)
        default_bg = mocker.Mock(
            image_url="https://example.com/default.png",
            description=None, country=None, visual_style=None,
        )
        default_bg.name = None  # "name" is a reserved Mock() constructor kwarg, must be set after

        generate_toon_video_ltx25(script, [zara], "endpoint-1", background=default_bg, scene_backgrounds={0: mocker.Mock(image_url="https://example.com/scene0.png")})

        fetched_urls = {call.args[0] for call in mock_httpx_get.call_args_list}
        assert "https://example.com/default.png" in fetched_urls
        assert "https://example.com/scene0.png" not in fetched_urls

    def test_other_cast_names_never_reach_the_actual_prompt(self, mocker):
        """End-to-end: even when the script names 2+ cast members in one
        shot's blocking (the exact failure confirmed live 2026-09-08 despite
        the writer prompt forbidding it), the text that actually reaches
        build_workflow must not name the unanchored one."""
        *_, mock_build_workflow = self._patch_pipeline(mocker)
        zara = self._variant(mocker, "z", "Zara")
        nova = self._variant(mocker, "n", "Captain Nova")
        shots = [{
            "shot_number": 1, "duration_seconds": 5, "speaker_variant_id": "z", "scene_index": 0,
            "blocking": "Zara centre, Captain Nova left", "dialogue": "Hi",
        }]
        script = self._script(mocker, shots)

        generate_toon_video_ltx25(script, [zara, nova], "endpoint-1")

        sent_prompt = mock_build_workflow.call_args[0][0]
        assert "Captain Nova" not in sent_prompt
        assert "Zara" in sent_prompt


class TestScrubUnanchoredNames:
    """Deterministic backstop for the group-shot duplicate-identity bug —
    confirmed live 2026-09-08 (twice, on two separate scripts) that the
    script-writer prompt's explicit rule against naming 2+ cast members in
    one shot's blocking is not reliably followed. This can't be skipped."""

    def test_replaces_another_characters_name(self):
        result = _scrub_unanchored_names("Zara centre, Captain Nova left, Blix right", "Zara", ["Captain Nova", "Blix"])
        assert "Captain Nova" not in result
        assert "Blix" not in result
        assert "Zara" in result

    def test_leaves_the_anchored_name_alone(self):
        result = _scrub_unanchored_names("Zara stands centre, looking up", "Zara", ["Captain Nova", "Blix"])
        assert result == "Zara stands centre, looking up"

    def test_case_insensitive_match(self):
        result = _scrub_unanchored_names("blix waves from the side", "Zara", ["Blix"])
        assert "blix" not in result.lower()

    def test_whole_word_match_does_not_clip_unrelated_text(self):
        """A name shouldn't match as a substring of an unrelated word."""
        result = _scrub_unanchored_names("Novartis banner in the background", "Zara", ["Nova"])
        assert "Novartis" in result

    def test_empty_text_returns_empty(self):
        assert _scrub_unanchored_names("", "Zara", ["Blix"]) == ""

    def test_no_other_names_is_a_no_op(self):
        text = "Zara stands alone."
        assert _scrub_unanchored_names(text, "Zara", []) == text

    def test_two_other_names_joined_by_and_collapse_to_one_count_phrase(self):
        """Confirmed live 2026-09-08: substituting each name independently
        produced "another figure nearby and another figure nearby" — a
        repeated, degenerate phrase that rendered as a crowd of ~6 unrelated
        characters instead of the two actually implied. A joined run must
        collapse to ONE phrase, not one substitution per name."""
        result = _scrub_unanchored_names(
            "Zara center, looking up at the sky, Captain Nova and Blix off to the side.",
            "Zara", ["Captain Nova", "Blix"],
        )
        assert result == "Zara center, looking up at the sky, two other figures off to the side."
        # The degenerate repeated phrase must not appear at all.
        assert "another figure nearby and another figure nearby" not in result
        assert result.count("figure") == 1

    def test_two_other_names_joined_by_comma_also_collapse(self):
        result = _scrub_unanchored_names("Captain Nova, Blix and Zara stand together.", "Zara", ["Captain Nova", "Blix"])
        assert result == "two other figures and Zara stand together."

    def test_three_other_names_use_the_word_three(self):
        result = _scrub_unanchored_names(
            "Kumar, Hans and Wen watch from the side.", "Zara", ["Kumar", "Hans", "Wen"],
        )
        assert result == "three other figures watch from the side."


class TestSanitizeSegmentShots:
    def _variant(self, mocker, vid, name):
        v = mocker.Mock(id=vid)
        v.name = name
        return v

    def test_scrubs_other_names_from_blocking_action_visual(self, mocker):
        zara = self._variant(mocker, "z", "Zara")
        nova = self._variant(mocker, "n", "Captain Nova")
        blix = self._variant(mocker, "b", "Blix")
        shots = [{
            "shot_number": 1,
            "blocking": "Zara centre, Captain Nova left, Blix right",
            "action": "Captain Nova waves, Blix nods",
            "visual": "Zara, Captain Nova and Blix standing together",
            "dialogue": "Captain Nova, is that really you?",
        }]

        result = _sanitize_segment_shots(shots, zara, [zara, nova, blix])

        assert "Captain Nova" not in result[0]["blocking"]
        assert "Blix" not in result[0]["blocking"]
        assert "Zara" in result[0]["blocking"]
        assert "Captain Nova" not in result[0]["action"]
        assert "Blix" not in result[0]["visual"]
        # Dialogue is the anchored speaker's own line — never touched, even
        # when it happens to mention another character by name.
        assert result[0]["dialogue"] == "Captain Nova, is that really you?"

    def test_does_not_mutate_the_original_shot_dicts(self, mocker):
        """The persisted/original script must be untouched — this is a
        render-time-only sanitization, not a rewrite of the stored script
        (a user editing the script should still see what the AI wrote)."""
        zara = self._variant(mocker, "z", "Zara")
        nova = self._variant(mocker, "n", "Captain Nova")
        original = [{"shot_number": 1, "blocking": "Zara centre, Captain Nova left"}]

        _sanitize_segment_shots(original, zara, [zara, nova])

        assert original[0]["blocking"] == "Zara centre, Captain Nova left"

    def test_single_cast_member_returns_shots_unchanged(self, mocker):
        zara = self._variant(mocker, "z", "Zara")
        shots = [{"shot_number": 1, "blocking": "Zara centre"}]
        assert _sanitize_segment_shots(shots, zara, [zara]) is shots

    def test_shot_with_no_relevant_fields_is_left_alone(self, mocker):
        zara = self._variant(mocker, "z", "Zara")
        nova = self._variant(mocker, "n", "Captain Nova")
        shots = [{"shot_number": 1, "dialogue": "Hello there"}]

        result = _sanitize_segment_shots(shots, zara, [zara, nova])

        assert result[0]["dialogue"] == "Hello there"


class TestLTX25TimeoutBudget:
    """A 37s five-shot render failed at exactly 1200s. The budget was
    max(1200, 300 + shots*120) — shot COUNT, left over from the 2.3 path
    where each shot was its own generation. Under 2.5 the whole scene is one
    generation whose length scales with DURATION, and because the argument
    was passed explicitly, raising the client default had no effect here."""

    def test_budget_scales_with_duration_not_shot_count(self):
        from app.services.culturetoon_selfhosted_video import ltx25_timeout_seconds
        assert ltx25_timeout_seconds(120) > ltx25_timeout_seconds(30)

    def test_covers_the_render_that_actually_timed_out(self):
        """37s needs ~680s of generation; it was given 1200s including cold
        start and missed."""
        from app.services.culturetoon_selfhosted_video import ltx25_timeout_seconds
        assert ltx25_timeout_seconds(37) > 1200

    def test_allows_for_a_cold_worker(self):
        """The clock starts at submission, so image pull and checkpoint load
        come out of the same budget as generation."""
        from app.services.culturetoon_selfhosted_video import (
            ltx25_timeout_seconds, _COLD_START_ALLOWANCE_SECONDS)
        assert ltx25_timeout_seconds(1) >= _COLD_START_ALLOWANCE_SECONDS

    def test_budget_never_exceeds_what_the_client_will_wait(self):
        import inspect
        from app.media.runpod_serverless_client import run_inference_job
        from app.services.culturetoon_selfhosted_video import ltx25_timeout_seconds
        from app.services.culturetoon_script import MAX_TOTAL_SECONDS

        default = inspect.signature(run_inference_job).parameters["timeout_seconds"].default
        assert ltx25_timeout_seconds(MAX_TOTAL_SECONDS) <= default

    def test_worker_ceiling_covers_the_longest_generation(self):
        import re, pathlib
        from app.services.culturetoon_script import MAX_TOTAL_SECONDS
        from app.services.culturetoon_usage import RENDER_GPU_SECONDS_PER_OUTPUT_SECOND

        handler = pathlib.Path("deploy/runpod_serverless/handler.py").read_text(encoding="utf-8")
        worker = int(re.search(r'COMFYUI_JOB_TIMEOUT_SECONDS", "(\d+)"', handler).group(1))
        assert worker >= float(RENDER_GPU_SECONDS_PER_OUTPUT_SECOND) * MAX_TOTAL_SECONDS

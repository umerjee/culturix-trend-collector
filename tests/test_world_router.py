"""Tests for app/routers/world.py — the public, unauthenticated read surface
for World Features (subject-centric public content). Every query here must
stay pre-filtered to is_world_content=True AND status='ready' with a real
video — no ordinary user's private Toons should ever be reachable through
this router.
"""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.toon import Toon
from app.models.toon_script import ToonScript
from app.models.trend import Trend
from app.models.cluster import Cluster
from app.routers import world


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Toon.__table__, ToonScript.__table__, Trend.__table__, Cluster.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _make_toon(db, *, is_world_content=True, status="ready", final_video_url="https://cdn/x.mp4",
               subject_region="IR", subject_text="The Strait of Hormuz", subject_category="place",
               title="The Strait of Hormuz", hook_line="A vital chokepoint.",
               era_label=None, era_year=None, world_published=True, shots=None):
    session = db()
    script = ToonScript(brand_id=uuid.uuid4(), hook_line=hook_line, generation_source="ai", status="approved", shots=shots)
    session.add(script)
    session.commit()
    session.refresh(script)
    toon = Toon(
        brand_id=uuid.uuid4(), script_id=script.id, title=title, status=status,
        final_video_url=final_video_url, is_world_content=is_world_content,
        subject_region=subject_region, subject_text=subject_text, subject_category=subject_category,
        era_label=era_label, era_year=era_year, world_published=world_published,
    )
    session.add(toon)
    session.commit()
    session.refresh(toon)
    toon_id = str(toon.id)
    if world_published is None:
        # An ORM insert applies the column default for None; a Feature that was
        # live before the gate existed has NULL from the ALTER, so set it directly.
        session.query(Toon).filter_by(id=toon.id).update({"world_published": None})
        session.commit()
    session.close()
    return toon_id


class TestPublishGate:
    """A finished render is not public until a person publishes it."""

    def test_unpublished_renders_are_hidden_everywhere(self, db):
        hidden = _make_toon(db, world_published=False, subject_region="FR")
        assert world.list_world_features()["total"] == 0
        assert world.list_world_regions()["regions"] == []
        with pytest.raises(HTTPException) as exc:
            world.get_world_feature(hidden)
        assert exc.value.status_code == 404

    def test_published_renders_are_visible(self, db):
        shown = _make_toon(db, world_published=True, subject_region="FR")
        assert world.list_world_features()["total"] == 1
        assert [r["feature_count"] for r in world.list_world_regions()["regions"]] == [1]
        assert world.get_world_feature(shown)["id"] == shown

    def test_features_live_before_the_gate_existed_stay_public(self, db):
        legacy = _make_toon(db, world_published=None)
        assert world.list_world_features()["total"] == 1
        assert world.get_world_feature(legacy)["id"] == legacy

    def test_new_toons_default_to_unpublished(self, db):
        session = db()
        toon = Toon(brand_id=uuid.uuid4(), script_id=uuid.uuid4(), status="ready")
        session.add(toon)
        session.commit()
        assert toon.world_published is False
        session.close()


class TestListWorldFeatures:
    def test_only_ready_world_content_with_a_video_is_returned(self, db):
        _make_toon(db)  # ready, world, has video — should appear
        _make_toon(db, is_world_content=False)  # ordinary user toon — must NOT appear
        _make_toon(db, status="animating")  # not ready yet — must NOT appear
        _make_toon(db, final_video_url=None)  # no video yet — must NOT appear

        result = world.list_world_features()
        assert result["total"] == 1
        assert len(result["features"]) == 1
        assert result["features"][0]["subject_text"] == "The Strait of Hormuz"

    def test_filters_by_region_and_category(self, db):
        _make_toon(db, subject_region="IR", subject_category="place")
        _make_toon(db, subject_region="JP", subject_category="species", subject_text="Deep-sea creatures")

        by_region = world.list_world_features(region="jp")  # lowercase input, stored uppercase
        assert len(by_region["features"]) == 1
        assert by_region["features"][0]["subject_region"] == "JP"

        by_category = world.list_world_features(category="place")
        assert len(by_category["features"]) == 1
        assert by_category["features"][0]["subject_category"] == "place"

    def test_search_matches_subject_text(self, db):
        _make_toon(db, subject_text="The Strait of Hormuz")
        _make_toon(db, subject_text="Mount Fuji")

        result = world.list_world_features(q="fuji")
        assert len(result["features"]) == 1
        assert result["features"][0]["subject_text"] == "Mount Fuji"


class TestListWorldRegions:
    def test_counts_only_ready_world_content(self, db):
        _make_toon(db, subject_region="IR")
        _make_toon(db, subject_region="IR")
        _make_toon(db, subject_region="JP", is_world_content=False)  # must not count

        result = world.list_world_regions()
        regions = {r["region"]: r["count"] for r in result["regions"]}
        assert regions == {"IR": 2}

    def test_includes_regions_with_trends_even_without_a_feature(self, db):
        _make_trend(db, region="JP", title="Japan trend")

        result = world.list_world_regions()

        japan = next(region for region in result["regions"] if region["region"] == "JP")
        assert japan["count"] == 0
        assert japan["feature_count"] == 0
        assert japan["trend_count"] == 1
        assert japan["trend_days"] == 1


class TestGetWorldFeature:
    def test_returns_feature_with_hook_line(self, db):
        toon_id = _make_toon(db, hook_line="A vital global oil chokepoint.")
        result = world.get_world_feature(toon_id)
        assert result["subject_text"] == "The Strait of Hormuz"
        assert result["hook_line"] == "A vital global oil chokepoint."

    def test_404s_for_a_non_ready_toon(self, db):
        toon_id = _make_toon(db, status="animating")
        with pytest.raises(HTTPException) as exc_info:
            world.get_world_feature(toon_id)
        assert exc_info.value.status_code == 404

    def test_404s_for_a_private_toon(self, db):
        toon_id = _make_toon(db, is_world_content=False)
        with pytest.raises(HTTPException) as exc_info:
            world.get_world_feature(toon_id)
        assert exc_info.value.status_code == 404

    def test_404s_for_an_invalid_id(self, db):
        with pytest.raises(HTTPException) as exc_info:
            world.get_world_feature("not-a-uuid")
        assert exc_info.value.status_code == 404


class TestFeatureTranscript:
    """The real narration text, always sourced from the shots the video's own audio speaks —
    never a separate, hand-written caption that could drift from what viewers actually hear."""

    SHOTS = [
        {"shot_number": 1, "dialogue": "In 753 BC, Rome was founded."},
        {"shot_number": 2, "dialogue": ""},  # a silent/subject-only shot: never a blank transcript line
        {"shot_number": 3, "dialogue": "  By 509 BC, it became a republic.  "},
        {"shot_number": 4, "dialogue": None},
    ]

    def test_english_transcript_is_the_real_dialogue_lines_in_order(self, db):
        toon_id = _make_toon(db, shots=self.SHOTS)
        result = world.get_world_feature(toon_id)
        assert result["transcript"] == ["In 753 BC, Rome was founded.", "By 509 BC, it became a republic."]
        assert result["transcript_language"] == "en" and result["translation_failed"] is False

    def test_a_script_with_no_shots_is_an_empty_transcript_not_an_error(self, db):
        toon_id = _make_toon(db, shots=None)
        assert world.get_world_feature(toon_id)["transcript"] == []

    def test_requesting_a_language_translates_the_hook_and_every_line(self, db, mocker):
        from app.translation import TranslationResult
        toon_id = _make_toon(db, hook_line="A vital chokepoint.", shots=self.SHOTS)

        def fake_translate_many(texts, target, **kw):
            return [TranslationResult(text=f"[{target}] {t}", target=target, ok=True, translated=True) for t in texts]
        translate = mocker.patch("app.translation.translate_many", side_effect=fake_translate_many)

        result = world.get_world_feature(toon_id, lang="fr")
        assert result["hook_line"] == "[fr] A vital chokepoint."
        assert result["transcript"] == ["[fr] In 753 BC, Rome was founded.", "[fr] By 509 BC, it became a republic."]
        assert result["transcript_language"] == "fr" and result["translation_failed"] is False
        # Exactly one batched call (hook + every real line together), not one request per line.
        assert translate.call_count == 1
        assert translate.call_args.args[0] == ["A vital chokepoint.", "In 753 BC, Rome was founded.", "By 509 BC, it became a republic."]

    def test_a_failed_translation_is_reported_not_silently_shown_as_english(self, db, mocker):
        from app.translation import TranslationResult
        toon_id = _make_toon(db, shots=self.SHOTS)

        def fake_translate_many(texts, target, **kw):
            return [TranslationResult(text=t, target=target, ok=False, translated=False, error="down") for t in texts]
        mocker.patch("app.translation.translate_many", side_effect=fake_translate_many)

        result = world.get_world_feature(toon_id, lang="fr")
        assert result["translation_failed"] is True

    def test_an_unrecognized_language_falls_back_to_english_untranslated(self, db):
        toon_id = _make_toon(db, hook_line="A vital chokepoint.", shots=self.SHOTS)
        result = world.get_world_feature(toon_id, lang="not-a-real-language")
        assert result["transcript_language"] == "en" and result["hook_line"] == "A vital chokepoint."

    def test_english_never_calls_the_translator(self, db, mocker):
        translate = mocker.patch("app.translation.translate_many")
        toon_id = _make_toon(db, shots=self.SHOTS)
        world.get_world_feature(toon_id, lang="en")
        translate.assert_not_called()

    def test_a_toon_with_no_stored_script_is_an_empty_transcript(self, db):
        session = db()
        toon = Toon(brand_id=uuid.uuid4(), script_id=uuid.uuid4(), title="Orphaned", status="ready",
                    final_video_url="https://cdn/x.mp4", is_world_content=True, world_published=True)
        session.add(toon)
        session.commit()
        toon_id = str(toon.id)
        session.close()
        result = world.get_world_feature(toon_id)
        assert result["transcript"] == [] and result["hook_line"] is None


def _make_trend(db, *, platform="tiktok", title="A trend", content="content text",
                 region="IR", likes=10, collected_at=None):
    session = db()
    trend = Trend(platform=platform, title=title, content=content, region=region, likes=likes,
                   collected_at=collected_at)
    session.add(trend)
    session.commit()
    session.close()


class TestListWorldTrends:
    def test_filters_by_region(self, db):
        _make_trend(db, region="IR", title="Iran trend")
        _make_trend(db, region="JP", title="Japan trend")

        result = world.list_world_trends(region="ir")  # lowercase input, stored uppercase
        assert len(result["trends"]) == 1
        assert result["trends"][0]["title"] == "Iran trend"

    def test_no_region_returns_everything(self, db):
        _make_trend(db, region="IR")
        _make_trend(db, region="JP")
        _make_trend(db, region=None)

        result = world.list_world_trends()
        assert result["total"] == 3

    def test_content_is_truncated_to_280_chars(self, db):
        _make_trend(db, content="x" * 500)
        result = world.list_world_trends(region="IR")
        assert len(result["trends"][0]["content"]) == 280

    def test_ordered_most_recent_first(self, db):
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        _make_trend(db, title="older", collected_at=now - timedelta(hours=1))
        _make_trend(db, title="newer", collected_at=now)

        result = world.list_world_trends(region="IR")
        assert result["trends"][0]["title"] == "newer"

    def test_date_range_filters_collected_at(self, db):
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        _make_trend(db, title="too old", collected_at=now - timedelta(days=10))
        _make_trend(db, title="in range", collected_at=now - timedelta(days=2))
        _make_trend(db, title="too new", collected_at=now)

        result = world.list_world_trends(
            region="IR",
            date_from=(now - timedelta(days=5)).isoformat(),
            date_to=(now - timedelta(days=1)).isoformat(),
        )
        assert [t["title"] for t in result["trends"]] == ["in range"]

    def test_invalid_date_400s(self, db):
        with pytest.raises(HTTPException) as exc_info:
            world.list_world_trends(region="IR", date_from="not-a-date")
        assert exc_info.value.status_code == 400

    def test_digest_prefers_cluster_context_and_labels_unclustered_sources(self, db):
        from app.models.cluster import Cluster
        session = db()
        cluster = Cluster(label=1, theme="Football transfer news", summary="Coverage of a major player move.", size=2)
        session.add(cluster)
        session.commit()
        clustered = Trend(platform="twitter", title="Player joins new club", content="news", region="GB", likes=100, cluster_id=cluster.id)
        unclustered = Trend(platform="tiktok", title="A viral dance challenge sound", content="sound", region="GB", likes=50)
        session.add_all([clustered, unclustered])
        session.commit()
        session.close()

        result = world.list_world_trend_digest(region="gb")

        groups = {group["kind"]: group for group in result["groups"]}
        assert groups["cluster"]["title"] == "Football transfer news"
        assert groups["cluster"]["summary"] == "Coverage of a major player move."
        assert groups["source"]["title"].startswith("Tiktok:")
        assert groups["source"]["summary"] == "Auto-grouped from similar signals."

    def test_digest_excludes_junk_signals_from_ever_becoming_their_own_group(self, db):
        # Confirmed live (2026-09-24): with no filter, the #1 "trend" in every region
        # checked (US/GB/FR/NG/IN/BR) was a bare TikTok audio-tag label or pure hashtag
        # spam with no real caption text. clean_title() already existed for the daily
        # brief; this is it finally applied to the trends digest too.
        _make_trend(db, platform="tiktok", title="[Audio: original sound - user9m01 by tomato]",
                   content="", region="KE", likes=500)
        _make_trend(db, platform="tiktok", title="#SeaLife #SailorLife #ShipLife #OceanVibes",
                   content="", region="KE", likes=400)
        _make_trend(db, platform="tiktok", title="@leah halton", content="", region="KE", likes=300)
        # A real, if trivial, caption survives — the filter targets non-content, not
        # low-substance-but-real text.
        _make_trend(db, platform="tiktok", title="Little little baby moments compilation",
                   content="", region="KE", likes=200)

        result = world.list_world_trend_digest(region="ke")

        titles = [g["title"] for g in result["groups"]]
        assert not any("audio" in t.lower() for t in titles)
        assert not any("sealife" in t.lower() for t in titles)
        assert not any("leah halton" in t.lower() for t in titles)
        assert any("little little baby" in t.lower() for t in titles)

    def test_digest_ranks_a_real_theme_above_a_larger_near_duplicate_spam_bucket(self, db):
        # Regression test for the live incident this quality scoring was built to fix:
        # a single repeated TikTok caption (163 near-identical posts, one platform) with
        # a huge signal_count outranked a real 4-signal curated Cluster theme under a
        # pure signal_count sort.
        from app.models.cluster import Cluster
        session = db()
        cluster = Cluster(label=1, theme="Nigerian News and Organizations",
                          summary="Newspapers and security services trending.", size=4, momentum="neutral")
        session.add(cluster)
        session.commit()
        session.add_all([
            Trend(platform="google_trends", title="nigerian newspapers", content="c", region="NG", likes=5, cluster_id=cluster.id),
            Trend(platform="google_trends", title="nigeria security and civil defence corps", content="c", region="NG", likes=4, cluster_id=cluster.id),
            Trend(platform="tiktok", title="ok", content="c", region="NG", likes=3, cluster_id=cluster.id),
            Trend(platform="tiktok", title="plateau state curfew update", content="c", region="NG", likes=2, cluster_id=cluster.id),
        ])
        # One repeated hashtag caption, many near-identical posts, one platform.
        for i in range(20):
            session.add(Trend(platform="tiktok", title="osmo action 6 raw clip #osmo #baguio",
                              content="c", region="NG", likes=1))
        session.commit()
        session.close()

        result = world.list_world_trend_digest(region="ng")

        titles = [g["title"] for g in result["groups"]]
        assert titles.index("Nigerian News and Organizations") < next(
            i for i, t in enumerate(titles) if t.lower().startswith("tiktok:")
        )

    def test_digest_accepts_supported_language(self, db, mocker):
        _make_trend(db, region="FR", title="football mondial", content="football mondial", likes=10)
        from types import SimpleNamespace
        mocker.patch("app.translation.translate_many", side_effect=lambda texts, lang: [
            SimpleNamespace(text=f"{t} [{lang}]", ok=True) for t in texts])

        result = world.list_world_trend_digest(region="fr", lang="fr")

        assert result["groups"][0]["summary"] == "Auto-grouped from similar signals. [fr]"


class TestWorldTrendsCoverage:
    def test_dense_region_reports_real_bounds_and_day_count(self, db):
        from datetime import datetime, timedelta
        base = datetime(2026, 7, 21, 12, 0, 0)
        for day_offset in range(5):
            _make_trend(db, region="US", collected_at=base + timedelta(days=day_offset))

        result = world.get_world_trends_coverage(region="us")  # lowercase input, normalized
        assert result["region"] == "US"
        assert result["days_with_data"] == 5
        assert result["earliest"].startswith("2026-07-21")
        assert result["latest"].startswith("2026-07-25")

    def test_empty_region_returns_nulls_and_zero(self, db):
        result = world.get_world_trends_coverage(region="IR")
        assert result == {"region": "IR", "earliest": None, "latest": None, "days_with_data": 0}

    def test_sparse_region_reports_a_single_day(self, db):
        from datetime import datetime
        _make_trend(db, region="TR", collected_at=datetime(2026, 9, 18, 13, 4))
        _make_trend(db, region="TR", collected_at=datetime(2026, 9, 18, 13, 9))

        result = world.get_world_trends_coverage(region="TR")
        assert result["days_with_data"] == 1


class TestEraFilteredFeatures:
    def test_era_range_returns_matching_feature(self, db):
        _make_toon(db, era_label="French Revolution", era_year=1789)

        result = world.list_world_features(era_year_min=1700, era_year_max=1900)
        assert result["total"] == 1
        assert result["features"][0]["era_label"] == "French Revolution"

    def test_era_range_excludes_out_of_range_feature(self, db):
        _make_toon(db, era_label="French Revolution", era_year=1789)

        result = world.list_world_features(era_year_min=1900, era_year_max=2000)
        assert result["total"] == 0

    def test_era_range_excludes_features_with_no_era_year(self, db):
        _make_toon(db)  # no era tagging at all

        result = world.list_world_features(era_year_min=1000, era_year_max=3000)
        assert result["total"] == 0

    def test_no_era_filter_still_returns_everything(self, db):
        _make_toon(db, era_label="French Revolution", era_year=1789)
        _make_toon(db, subject_region="JP", title="Mount Fuji")

        result = world.list_world_features()
        assert result["total"] == 2

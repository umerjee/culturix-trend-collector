"""Trend-to-culture editorial workflow (app/services/editorial.py, app/routers/editorial.py):
safety as a hard gate, transparent ranking, continent balance, source-only grounding, the
render/publish gate on every path, and post/metric recording feeding the existing analytics."""
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.character import Character
from app.models.character_brand import CharacterBrand
from app.models.character_variant import CharacterVariant
from app.models.cluster import Cluster
from app.models.curated_item import CuratedItem
from app.models.editorial_candidate import EditorialCandidate
from app.models.generation_usage import GenerationUsage
from app.models.toon import Toon
from app.models.toon_post import ToonPost
from app.models.toon_script import ToonScript
from app.models.trend import Trend
from app.routers import editorial as router
from app.services import editorial as ed

SOURCE = ("The Benin Bronzes are thousands of metal plaques and sculptures made in the Kingdom of Benin. "
          "Craftsmen of the royal guild cast them from the 13th century onwards using the lost-wax method. "
          "Many plaques decorated the palace of the Oba in Benin City. "
          "They depict court life, warriors, animals and Europeans who traded with the kingdom. ") * 2
CHECKLIST = {k: True for k in ed.SAFETY_CHECKLIST}


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        EditorialCandidate.__table__, CuratedItem.__table__, Trend.__table__, Cluster.__table__,
        Toon.__table__, ToonScript.__table__, ToonPost.__table__, CharacterBrand.__table__,
        Character.__table__, CharacterVariant.__table__, GenerationUsage.__table__,
    ])
    factory = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", factory)
    return factory


def _item(session, region="NG", title="Benin Bronzes", text=SOURCE, decision="include", url="https://en.wikipedia.org/wiki/Benin_Bronzes", priority=80):
    item = CuratedItem(source_type="wikipedia", source_ref=title, region=region, source_url=url, title=title,
                       summary=text[:200], raw_text=text, category="history", priority_score=priority,
                       pipeline_decision=decision)
    session.add(item)
    session.commit()
    return item


def _cluster_trend(session, region="NG", theme="Bronze statue selfies go viral", summary="People pose with metal statues in museums.", momentum="up", quality=0.8):
    cluster = Cluster(label=1, theme=theme, summary=summary, momentum=momentum, quality_score=quality)
    session.add(cluster)
    session.commit()
    for platform in ("tiktok", "youtube"):
        session.add(Trend(platform=platform, title=theme, content=summary, region=region, cluster_id=cluster.id,
                          collected_at=datetime.utcnow() - timedelta(days=1), likes=500))
    session.commit()
    return cluster


def _cast(session, home_region="NG"):
    user_id = uuid.uuid4()
    brand = CharacterBrand(user_id=user_id, name="Toons")
    session.add(brand)
    session.commit()
    character = Character(brand_id=brand.id, name="Ada", description="A Nigerian woman", home_region=home_region)
    session.add(character)
    session.commit()
    variant = CharacterVariant(character_id=character.id, name="Ada")
    session.add(variant)
    session.commit()
    return SimpleNamespace(user_id=str(user_id), brand_id=str(brand.id), variant_id=str(variant.id))


def _candidate(session, **overrides):
    values = dict(trend_type="cluster", trend_id=1, trend_title="Bronze statue selfies", region="NG",
                  continent="Africa", curated_item_id=uuid.uuid4(), source_type="wikipedia",
                  source_title="Benin Bronzes", source_url="https://en.wikipedia.org/wiki/Benin_Bronzes",
                  source_excerpt=SOURCE, rank_score=0.7, status="candidate", safety_status="pending")
    values.update(overrides)
    c = EditorialCandidate(**values)
    session.add(c)
    session.commit()
    session.refresh(c)
    session.expunge(c)  # keep loaded fields readable after the throwaway session goes away
    return c


def _script_result(dialogue="Craftsmen cast them from the 13th century onwards using the lost-wax method."):
    return {"hook_line": "Selfies with bronze? Benin did it first.", "tone": "funny", "total_duration_seconds": 12,
            "shots": [{"shot_number": 1, "duration_seconds": 6, "action": "Ada poses", "dialogue": dialogue},
                      {"shot_number": 2, "duration_seconds": 6, "action": "Ada winks", "dialogue": "Strike a pose!"}]}


@pytest.fixture
def writer(mocker):
    return SimpleNamespace(
        write=mocker.patch("app.services.culturetoon_script.generate_toon_script_from_idea", return_value=_script_result()),
        judge=mocker.patch("app.services.editorial.judge_editorial_grounding",
                           return_value={"grounded": True, "unsupported_claims": [], "judge_failed": False}),
        fix=mocker.patch("app.services.culturetoon_script.fix_unsupported_claims", return_value=None),
        craft=mocker.patch("app.services.culturetoon_script.judge_script_comedy",
                           return_value={"comedy_score": 74, "passes_bar": True, "feedback": "ok", "judge_failed": False}),
        context=mocker.patch("app.routers.culturetoons._gather_script_generation_context",
                             return_value=({}, [], [], [], "")),
    )


def _script_body(cast, **overrides):
    body = {"user_id": cast.user_id, "brand_id": cast.brand_id, "character_variant_ids": [cast.variant_id],
            "format": "trend_to_history", "language": "en", "tone": "funny", "num_shots": 2,
            "target_duration_seconds": 12}
    body.update(overrides)
    return body


def _approved(db, writer):
    session = db()
    cast = _cast(session)
    c = _candidate(session)
    router.review_safety(str(c.id), {"decision": "clear", "checklist": CHECKLIST, "reviewer": "ops@example.com"})
    router.generate_candidate_script(str(c.id), _script_body(cast))
    out = router.approve_candidate(str(c.id), {"reviewer": "ops@example.com"})
    return out, cast


# ── Pure logic ────────────────────────────────────────────────────────────────

class TestCoverage:
    def test_continents_cover_the_four_targets(self):
        assert [ed.continent_for(r) for r in ("ng", "BR", "JP", "FR", "TR")] == ["Africa", "Americas", "Asia", "Europe", "Asia"]
        assert ed.continent_for(None) == "Other"

    def test_balance_slate_round_robins_continents_so_one_cannot_fill_the_top(self):
        europe = [{"id": f"e{i}", "continent": "Europe", "rank_score": 0.9 - i / 100} for i in range(5)]
        africa = [{"id": "a0", "continent": "Africa", "rank_score": 0.3}]
        asia = [{"id": "s0", "continent": "Asia", "rank_score": 0.5}]
        ids = [c["id"] for c in ed.balance_slate(europe + africa + asia)]
        assert ids[:3] == ["e0", "s0", "a0"]
        assert ids[3:] == ["e1", "e2", "e3", "e4"]

    def test_coverage_reports_target_continents_with_nothing(self):
        summary = ed.coverage_summary([{"continent": "Europe"}, {"continent": "Asia"}])
        assert summary["gaps"] == ["Americas", "Africa"]
        assert summary["by_continent"]["Europe"] == 1


class TestSafetyScreen:
    def test_tragedy_or_conflict_in_the_trend_is_a_hard_exclusion(self):
        screen = ed.screen_safety("Flood death toll rises as troops deployed", "A calm museum.")
        assert {e["category"] for e in screen["exclusions"]} == {"tragedy", "active_conflict"}
        assert all(e["where"] == "trend" for e in screen["exclusions"])

    def test_religious_worship_in_the_trend_is_excluded(self):
        assert ed.screen_safety("Friday prayers livestream", SOURCE)["exclusions"][0]["category"] == "religious_worship"

    def test_a_post_about_faith_is_excluded_even_without_ritual_words(self):
        # Found on real data: a Quran recitation post passed a practice-words-only list.
        screen = ed.screen_safety("Quran talawat Ma sha Allah #islam post #foryou", SOURCE)
        assert screen["exclusions"][0]["category"] == "religious_worship"

    @pytest.mark.parametrize("text", [
        "Kaby ki ronak kaby ka manzar#makahhmukarma 🕋 #Madina",  # inside hashtags + emoji (real post)
        "#createsightinsight أروع صوت أذان ألقارئ",  # Arabic call to prayer (real post)
        "Ma sha Allah",
    ])
    def test_religious_posts_are_caught_in_hashtags_other_scripts_and_emoji(self, text):
        assert ed.screen_safety(text, "")["exclusions"][0]["category"] == "religious_worship"

    def test_place_names_containing_a_religious_word_are_not_blocked(self):
        assert ed.screen_safety("Allahabad street food tour", "")["exclusions"] == []

    def test_whole_words_only(self):
        assert ed.screen_safety("Star Wars day memes and warm weather", SOURCE)["exclusions"] == []

    def test_atrocity_in_the_source_is_excluded_but_old_battles_and_faith_are_only_review_flags(self):
        assert ed.screen_safety("Statue selfies", "A memorial to the victims of a genocide.")["exclusions"]
        screen = ed.screen_safety("Statue selfies", "A cathedral built after a famous battle.")
        assert screen["exclusions"] == []
        assert {r["category"] for r in screen["review"]} == {"historic_conflict", "religion"}


class TestRanking:
    def _rank(self, **kw):
        args = dict(trend_text="Bronze statue selfies", trend_momentum="up", trend_quality=0.8, source_text=SOURCE,
                    source_priority=80, times_used=0, region="NG", cast_regions=None)
        args.update(kw)
        return ed.rank_candidate(**args)

    def test_every_factor_is_weighted_and_explained(self):
        score, factors = self._rank()
        assert [f["factor"] for f in factors] == list(ed.RANK_WEIGHTS)
        assert all(f["reason"] for f in factors)
        assert score == pytest.approx(sum(f["score"] * f["weight"] for f in factors), abs=1e-3)

    def test_momentum_novelty_and_thin_sources_move_the_score(self):
        base, _ = self._rank()
        assert self._rank(trend_momentum="down")[0] < base
        assert self._rank(times_used=2)[0] < base
        thin_score, thin = self._rank(source_text="Short.")
        assert thin_score < base and "thin source" in thin[1]["reason"]

    def test_shared_words_are_named_in_the_relevance_reason(self):
        _, factors = self._rank()
        relevance = next(f for f in factors if f["factor"] == "cultural_relevance")
        assert "bronze" in relevance["reason"] and relevance["score"] > 0.5

    def test_generic_words_do_not_count_as_a_connection(self):
        # Found on real data: "after"/"experience" made a laughter video look perfectly matched to a temple.
        _, factors = self._rank(trend_text="Is laughter contagious? After this experience, real love",
                                source_focus="Valley of the Temples. After years of experience, real history.")
        assert next(f for f in factors if f["factor"] == "cultural_relevance")["score"] == 0.5

    def test_relevance_compares_with_what_the_source_is_about_not_its_whole_text(self):
        _, factors = self._rank(trend_text="Museum selfies", source_focus="Benin Bronzes. Royal plaques.",
                                source_text=SOURCE + " Visitors take selfies in the museum.")
        assert next(f for f in factors if f["factor"] == "cultural_relevance")["score"] == 0.5

    def test_a_search_spike_counts_as_more_than_one_post(self):
        post, _ = self._rank(trend_kind="trend", trend_momentum=None, trend_quality=None)
        search, factors = self._rank(trend_kind="search", trend_momentum=None, trend_quality=None)
        assert search > post and "search spike" in factors[0]["reason"].lower()

    def test_a_single_post_is_weaker_evidence_than_a_cluster(self):
        cluster_score, _ = self._rank()
        single_score, factors = self._rank(trend_kind="trend", trend_momentum=None, trend_quality=None)
        assert single_score < cluster_score
        assert "single post" in factors[0]["reason"]

    def test_cast_fit_prefers_a_cast_member_from_the_country(self):
        fits = [next(f for f in self._rank(cast_regions=regions)[1] if f["factor"] == "cast_fit")["score"]
                for regions in (["NG"], ["KE"], ["FR"])]
        assert fits[0] > fits[1] > fits[2]


class TestGroundingHelpers:
    def test_brief_fences_the_source_and_labels_the_trend_as_context_only(self):
        c = SimpleNamespace(region="NG", trend_title="Bronze selfies", trend_summary=None, source_title="Benin Bronzes",
                            source_type="wikipedia", source_excerpt=SOURCE)
        brief = ed.build_script_brief(c, "then_vs_now", "fr")
        assert "NOT a source of facts" in brief and "lost-wax" in brief and "French" in brief
        assert brief.index("<<<") < brief.index("lost-wax") < brief.index(">>>")

    def test_claims_are_linked_to_the_supporting_source_sentence(self):
        result = _script_result()
        claims = ed.link_claims_to_source(result, SOURCE, unsupported=[])
        fact_line = next(c for c in claims if c["shot_number"] == 1)
        assert "lost-wax" in fact_line["source_sentence"] and fact_line["supported"]

    def test_a_flagged_claim_marks_its_line_unsupported(self):
        result = _script_result(dialogue="The bronzes were made in 1066 by Vikings.")
        claims = ed.link_claims_to_source(result, SOURCE, unsupported=["made in 1066 by Vikings"])
        assert next(c for c in claims if c["shot_number"] == 1)["supported"] is False

    def test_comedy_fact_check_treats_the_characters_as_fiction_and_the_trend_as_context_only(self, mocker):
        llm = mocker.patch("app.services.culturetoon_script._call_llm_json",
                           return_value={"unsupported_claims": ["Benin bronzes were made by aliens"], "grounded": False})
        result = ed.judge_editorial_grounding(_script_result(), SOURCE, "Bronze statue selfies go viral")
        prompt = llm.call_args.args[0]
        assert "FICTION" in prompt and "never flag those" in prompt
        assert "may ONLY support saying that this current event is happening" in prompt
        assert result == {"grounded": False, "unsupported_claims": ["Benin bronzes were made by aliens"],
                          "judge_failed": False, "checker": "comedy"}

    def test_comedy_fact_check_dismisses_claims_the_source_states_and_fails_open(self, mocker):
        stated = "Craftsmen of the royal guild cast them from the 13th century onwards using the lost-wax method."
        mocker.patch("app.services.culturetoon_script._call_llm_json", return_value={"unsupported_claims": [stated]})
        assert ed.judge_editorial_grounding(_script_result(), SOURCE, "")["grounded"] is True
        from app.services.culturetoon_script import ToonScriptGenerationError
        mocker.patch("app.services.culturetoon_script._call_llm_json", side_effect=ToonScriptGenerationError("down"))
        failed = ed.judge_editorial_grounding(_script_result(), SOURCE, "")
        assert failed["judge_failed"] is True and ed.grounding_status(failed) == "unchecked"

    def test_brief_keeps_religious_buildings_out_of_the_jokes_only_when_the_source_has_them(self):
        base = dict(region="IN", trend_title="india vs sri lanka", trend_summary=None, source_title="Agra Fort", source_type="unesco")
        with_mosques = ed.build_script_brief(SimpleNamespace(**base, source_excerpt="It has two beautiful mosques."), "trend_to_history", "en")
        plain = ed.build_script_brief(SimpleNamespace(**base, source_excerpt="Red sandstone walls 2.5 km long."), "trend_to_history", "en")
        assert "keep them out of every joke" in with_mosques and "keep them out of every joke" not in plain
        assert "never present an invented event as real news" in plain

    def test_grounding_status(self):
        assert ed.grounding_status({"grounded": True, "judge_failed": False}) == "grounded"
        assert ed.grounding_status({"grounded": False, "judge_failed": False}) == "unsupported"
        assert ed.grounding_status({"grounded": None, "judge_failed": True}) == "unchecked"


# ── Candidates from real rows ─────────────────────────────────────────────────

class TestBuildCandidates:
    def test_pairs_recent_trends_with_same_country_sources(self, db):
        session = db()
        _cluster_trend(session)
        _item(session)
        result = ed.build_candidates(session)
        session.commit()
        (c,) = result["created"]
        assert (c.region, c.continent, c.status, c.trend_type) == ("NG", "Africa", "candidate", "cluster")
        assert c.source_url and "lost-wax" in c.source_excerpt and c.rank_score > 0
        assert c.trend_platforms == ["tiktok", "youtube"]

    def test_blocked_pairs_are_shown_but_never_scored(self, db):
        session = db()
        _cluster_trend(session, region="FR", theme="Train crash death toll", summary="Victims mourned.")
        _item(session, region="FR", title="Carcassonne")
        (c,) = ed.build_candidates(session)["created"]
        assert c.status == "blocked" and c.safety_status == "blocked" and c.rank_score is None
        assert c.safety_flags[0]["category"] == "tragedy"

    def test_never_duplicates_and_skips_countries_missing_one_side(self, db):
        session = db()
        _cluster_trend(session)
        _item(session)
        _item(session, region="BR", title="Christ the Redeemer")
        first = ed.build_candidates(session)
        session.commit()
        second = ed.build_candidates(session)
        assert len(first["created"]) == 1 and second["created"] == []
        assert {"region": "BR", "reason": "no recent trends"} in second["skipped_regions"]

    def test_excluded_or_uncitable_sources_are_not_used(self, db):
        session = db()
        _cluster_trend(session)
        _item(session, decision="exclude")
        _item(session, title="No link", url=None)
        assert ed.build_candidates(session)["created"] == []

    def test_hashtag_only_posts_are_skipped_but_other_scripts_are_kept(self, db):
        session = db()
        _item(session, region="JP", title="Tokaido Shinkansen", text="The Tokaido Shinkansen opened in 1964. " * 20)
        for title in ("all luv #school #friends #real", "東京の新しいラーメン店が大人気になっています"):
            session.add(Trend(platform="tiktok", title=title, region="JP", collected_at=datetime.utcnow()))
        session.commit()
        (c,) = ed.build_candidates(session)["created"]
        assert c.trend_title.startswith("東京")

    def test_one_trend_or_source_cannot_take_every_slot_for_a_country(self, db):
        session = db()
        _cluster_trend(session)
        for title in ("Benin Bronzes", "Benin City Walls", "Oba of Benin"):
            _item(session, title=title)
        created = ed.build_candidates(session)["created"]
        assert len(created) == 1  # one trend, so one pairing, not three

    def test_a_sound_label_title_falls_back_to_the_posts_own_words(self, db):
        session = db()
        _item(session)
        session.add(Trend(platform="tiktok", title="[Audio: original sound - someone]", region="NG",
                          content="Grandma explains how bronze statues were really made", collected_at=datetime.utcnow()))
        session.commit()
        (c,) = ed.build_candidates(session)["created"]
        assert c.trend_title.startswith("Grandma explains")

    def test_refresh_blocks_open_candidates_the_improved_screen_now_catches(self, db):
        session = db()
        stale = _candidate(session, trend_title="Kaby ki ronak #makahhmukarma #Madina")
        approved = _candidate(session, trend_id=2, trend_title="Ma sha Allah", status="approved", safety_status="cleared")
        result = ed.build_candidates(session)
        session.commit()
        assert [str(c.id) for c in result["rescreened_blocked"]] == [str(stale.id)]
        rows = {str(c.id): c for c in db().query(EditorialCandidate).all()}
        assert rows[str(stale.id)].status == "blocked" and rows[str(stale.id)].rank_score is None
        assert rows[str(approved.id)].status == "approved"  # a person already signed this one off

    def test_google_trends_rows_are_ranked_as_search_spikes(self, db):
        session = db()
        _item(session)
        session.add(Trend(platform="google_trends", title="nigeria vs ghana", content="Trending on Google Search (500000+ searches).",
                          region="NG", collected_at=datetime.utcnow()))
        session.commit()
        (c,) = ed.build_candidates(session)["created"]
        assert "search spike" in c.rank_factors[0]["reason"].lower()

    def test_an_open_trend_is_not_paired_again_and_duplicates_are_retired(self, db):
        session = db()
        _cluster_trend(session)
        _item(session, title="Benin Bronzes")
        (kept,) = ed.build_candidates(session)["created"]
        kept_key = (kept.trend_type, kept.trend_id)
        session.commit()
        _item(db(), title="Benin City Walls")
        session = db()
        assert ed.build_candidates(session)["created"] == []  # same trend already open
        session.commit()
        dup = _candidate(db(), trend_type=kept_key[0], trend_id=kept_key[1], rank_score=0.1)
        session = db()
        result = ed.build_candidates(session)
        session.commit()
        assert [str(c.id) for c in result["superseded"]] == [str(dup.id)]
        assert db().query(EditorialCandidate).filter_by(id=dup.id).one().status == "rejected"

    def test_a_scripted_candidate_holds_its_trend_but_other_countries_keep_theirs(self, db):
        session = db()
        _candidate(session, status="scripted", rank_score=0.2)
        dup = _candidate(session, rank_score=0.9)  # same trend, same country, not yet reviewed
        other_country = _candidate(session, region="GH", continent="Africa", rank_score=0.9)
        result = ed.build_candidates(db())
        assert [str(c.id) for c in result["superseded"]] == [str(dup.id)]
        assert str(other_country.id) not in {str(c.id) for c in result["superseded"]}

    def test_old_trends_are_ignored(self, db):
        session = db()
        _item(session)
        session.add(Trend(platform="tiktok", title="Old news", region="NG", collected_at=datetime.utcnow() - timedelta(days=30)))
        session.commit()
        assert ed.build_candidates(session)["created"] == []

    def test_list_endpoint_separates_blocked_and_reports_coverage(self, db):
        session = db()
        _candidate(session)
        _candidate(session, region="FR", continent="Europe", status="blocked", safety_status="blocked", rank_score=None)
        out = router.list_candidates()
        assert [c["region"] for c in out["candidates"]] == ["NG"]
        assert [c["region"] for c in out["blocked"]] == ["FR"]
        assert out["coverage"]["gaps"] == ["Asia", "Americas", "Europe"]


# ── Review, script, approval ──────────────────────────────────────────────────

class TestSafetyReview:
    def test_clearing_requires_the_whole_checklist(self, db):
        c = _candidate(db())
        with pytest.raises(HTTPException) as exc:
            router.review_safety(str(c.id), {"decision": "clear", "checklist": {**CHECKLIST, "framing_checked": False}})
        assert exc.value.status_code == 400 and exc.value.detail["missing"] == ["framing_checked"]
        out = router.review_safety(str(c.id), {"decision": "clear", "checklist": CHECKLIST, "reviewer": "ops@example.com"})
        assert out["safety"]["status"] == "cleared" and out["safety"]["reviewed_by"] == "ops@example.com"

    def test_an_automatic_exclusion_cannot_be_cleared(self, db):
        c = _candidate(db(), safety_flags=[{"category": "tragedy", "terms": ["massacre"], "where": "source"}])
        with pytest.raises(HTTPException) as exc:
            router.review_safety(str(c.id), {"decision": "clear", "checklist": CHECKLIST})
        assert exc.value.status_code == 409

    def test_blocking_needs_a_note_and_is_terminal(self, db):
        c = _candidate(db())
        with pytest.raises(HTTPException):
            router.review_safety(str(c.id), {"decision": "block"})
        assert router.review_safety(str(c.id), {"decision": "block", "note": "Mocks a real person"})["status"] == "blocked"
        with pytest.raises(HTTPException) as exc:
            router.review_safety(str(c.id), {"decision": "clear", "checklist": CHECKLIST})
        assert exc.value.status_code == 409


class TestScript:
    def test_writes_a_source_grounded_script_with_the_brands_cast(self, db, writer):
        session = db()
        cast = _cast(session)
        c = _candidate(session)
        out = router.generate_candidate_script(str(c.id), _script_body(cast, format="then_vs_now", language="es"))
        assert out["status"] == "scripted" and out["grounding_status"] == "grounded"
        assert (out["format"], out["language"]) == ("then_vs_now", "es")
        brief = writer.write.call_args.args[0]
        assert "lost-wax" in brief and "Spanish" in brief
        script = db().query(ToonScript).one()
        assert script.character_variant_ids == [cast.variant_id] and script.trend_source_id == 1
        assert script.comedy_judgment["grounding"]["grounded"] is True
        assert script.comedy_judgment["editorial_candidate_id"] == str(c.id)

    def test_the_trend_never_reaches_the_fact_checker_as_a_source_of_facts(self, db, writer):
        session = db()
        cast = _cast(session)
        c = _candidate(session, trend_title="Viral claim: bronzes were made by aliens")
        router.generate_candidate_script(str(c.id), _script_body(cast))
        _, facts_given_to_judge, trend_context = writer.judge.call_args.args
        assert facts_given_to_judge == SOURCE and "aliens" not in facts_given_to_judge
        assert "aliens" in trend_context  # passed separately, labelled as current-event context only

    def test_unsupported_claims_get_one_comedy_revision_not_the_narration_fixer(self, db, writer):
        session = db()
        cast = _cast(session)
        c = _candidate(session)
        writer.judge.return_value = {"grounded": False, "unsupported_claims": ["made in 1066"], "judge_failed": False}
        out = router.generate_candidate_script(str(c.id), _script_body(cast))
        assert writer.fix.call_count == 0  # the World fixer rewrites jokes into plain narration
        assert writer.write.call_count == 2
        revision = writer.write.call_args_list[1].kwargs
        assert "made in 1066" in revision["critique_feedback"] and "comedy" in revision["critique_feedback"].lower()
        assert revision["previous_draft"]["hook_line"] == _script_result()["hook_line"]
        assert out["grounding_status"] == "unsupported"

    def test_a_revision_that_removes_the_claim_is_kept(self, db, writer):
        session = db()
        cast = _cast(session)
        c = _candidate(session)
        fixed = _script_result(dialogue="Cast from the 13th century, and still better posers than us!")
        writer.write.side_effect = [_script_result(), fixed]
        writer.judge.side_effect = [{"grounded": False, "unsupported_claims": ["x"], "judge_failed": False},
                                    {"grounded": True, "unsupported_claims": [], "judge_failed": False}]
        out = router.generate_candidate_script(str(c.id), _script_body(cast))
        assert out["grounding_status"] == "grounded" and out["grounding"]["auto_fixed"] is True
        assert out["script"]["shots"][0]["dialogue"] == fixed["shots"][0]["dialogue"]

    def test_rejects_unknown_format_language_or_missing_cast(self, db, writer):
        session = db()
        cast = _cast(session)
        c = _candidate(session)
        for bad in ({"format": "roast"}, {"language": "it"}, {"character_variant_ids": []}):
            with pytest.raises(HTTPException) as exc:
                router.generate_candidate_script(str(c.id), _script_body(cast, **bad))
            assert exc.value.status_code == 400
        assert writer.write.call_count == 0

    def test_a_cast_from_another_account_is_refused(self, db, writer):
        session = db()
        cast, other = _cast(session), _cast(session)
        c = _candidate(session)
        with pytest.raises(HTTPException) as exc:
            router.generate_candidate_script(str(c.id), _script_body(cast, character_variant_ids=[other.variant_id]))
        assert exc.value.status_code == 404


class TestApprovalAndGate:
    def test_approval_needs_cleared_safety_and_grounded_claims(self, db, writer):
        session = db()
        cast = _cast(session)
        c = _candidate(session)
        router.generate_candidate_script(str(c.id), _script_body(cast))
        with pytest.raises(HTTPException) as exc:
            router.approve_candidate(str(c.id))
        assert "safety" in exc.value.detail.lower()

        c2 = _candidate(db(), trend_id=2)
        router.review_safety(str(c2.id), {"decision": "clear", "checklist": CHECKLIST})
        writer.judge.return_value = {"grounded": False, "unsupported_claims": ["x"], "judge_failed": False}
        router.generate_candidate_script(str(c2.id), _script_body(cast))
        with pytest.raises(HTTPException) as exc:
            router.approve_candidate(str(c2.id))
        assert "grounded" in exc.value.detail

    def test_approval_creates_the_toon_and_opens_the_gate(self, db, writer):
        out, _ = _approved(db, writer)
        assert out["status"] == "approved" and out["toon_id"] and out["approved_by"] == "ops@example.com"
        session = db()
        toon = session.query(Toon).one()
        assert toon.status == "idea" and str(toon.id) == out["toon_id"]
        assert ed.editorial_gate(session, toon.script_id) is None

    def test_gate_is_closed_before_approval_and_ignores_ordinary_scripts(self, db, writer):
        session = db()
        cast = _cast(session)
        c = _candidate(session)
        router.generate_candidate_script(str(c.id), _script_body(cast))
        script_id = db().query(ToonScript).one().id
        assert "safety" in ed.editorial_gate(db(), script_id).lower()
        assert ed.editorial_gate(db(), uuid.uuid4()) is None

    def test_editing_the_script_after_approval_closes_the_gate_until_reapproved(self, db, writer):
        _approved(db, writer)
        session = db()
        script = session.query(ToonScript).one()
        script.shots = [{**script.shots[0], "dialogue": "Made in 1066, obviously."}]
        session.commit()
        assert "changed after approval" in ed.editorial_gate(db(), script.id)
        c = db().query(EditorialCandidate).one()
        router.recheck_grounding(str(c.id))
        router.approve_candidate(str(c.id))
        assert ed.editorial_gate(db(), script.id) is None

    def test_render_and_publish_routes_refuse_an_ungated_editorial_script(self, db, writer):
        from app.routers import culturetoons
        session = db()
        cast = _cast(session)
        c = _candidate(session)
        router.generate_candidate_script(str(c.id), _script_body(cast))
        session = db()
        script = session.query(ToonScript).one()
        toon = Toon(brand_id=script.brand_id, character_variant_id=script.character_variant_id, script_id=script.id,
                    status="ready", final_video_url="https://example.com/v.mp4")
        session.add(toon)
        session.commit()
        body = {"user_id": cast.user_id, "brand_id": cast.brand_id, "platform": "tiktok"}
        for call in (lambda: culturetoons.generate_toon_video(str(toon.id), body, None),
                     lambda: culturetoons.publish_toon(str(toon.id), body, None)):
            with pytest.raises(HTTPException) as exc:
                call()
            assert exc.value.status_code == 409

    def test_batch_renderer_skips_an_editorial_script_approved_from_the_scripts_tab(self, db, writer):
        from app.services.culturetoon_selfhosted_batch import find_approved_scripts_without_toon
        session = db()
        cast = _cast(session)
        c = _candidate(session)
        router.generate_candidate_script(str(c.id), _script_body(cast))
        session = db()
        editorial_script = session.query(ToonScript).one()
        editorial_script.status = "approved"
        ordinary = ToonScript(brand_id=editorial_script.brand_id, status="approved", shots=[])
        session.add(ordinary)
        session.commit()
        found = find_approved_scripts_without_toon(db(), editorial_script.brand_id)
        assert [s.id for s in found] == [ordinary.id]


# ── Recording posts and learning ──────────────────────────────────────────────

class TestPostsAndPerformance:
    def _post(self, cid, **overrides):
        body = {"platform": "tiktok", "post_url": "https://www.tiktok.com/@toons/video/1", "views": 2000,
                "likes": 150, "comments": 12, "shares": 8, "saves": 30, "avg_watch_seconds": 7.5}
        body.update(overrides)
        return router.record_post(cid, body)

    def test_only_approved_videos_can_be_recorded(self, db):
        c = _candidate(db())
        with pytest.raises(HTTPException) as exc:
            self._post(str(c.id))
        assert exc.value.status_code == 409

    def test_records_a_tracked_post_with_metrics(self, db, writer):
        out, _ = _approved(db, writer)
        result = self._post(out["id"])
        assert result["candidate"]["status"] == "published"
        post = db().query(ToonPost).one()
        assert (post.status, post.platform, post.latest_views, post.latest_comments) == ("tracked", "tiktok", 2000, 12)
        assert post.extra_metrics == {"saves": 30, "avg_watch_seconds": 7.5}

    @pytest.mark.parametrize("bad", [{"platform": "myspace"}, {"post_url": "tiktok.com/x"}, {"views": -1},
                                     {"comments": None}, {"completion_rate": 1.5}, {"likes": 2.5}])
    def test_invalid_post_input_is_rejected(self, db, writer, bad):
        out, _ = _approved(db, writer)
        with pytest.raises(HTTPException) as exc:
            self._post(out["id"], **bad)
        assert exc.value.status_code == 400

    def test_metrics_updates_replace_earlier_readings(self, db, writer):
        out, _ = _approved(db, writer)
        post_id = self._post(out["id"])["post_id"]
        router.update_post_metrics(post_id, {"views": 5000, "follows": 4})
        post = db().query(ToonPost).one()
        assert post.latest_views == 5000 and post.latest_comments == 12
        assert post.extra_metrics == {"saves": 30, "avg_watch_seconds": 7.5, "follows": 4}

    def test_performance_view_records_every_learning_dimension_and_rates(self, db, writer):
        out, cast = _approved(db, writer)
        self._post(out["id"])
        perf = router.performance()
        (row,) = perf["rows"]
        for key in ("platform", "region", "continent", "language", "trend_id", "curated_item_id", "format",
                    "hook", "cast", "tone", "duration_seconds", "post_url"):
            assert row[key] not in (None, []), key
        assert row["comments_per_1k"] == 6.0 and row["shares_per_1k"] == 4.0 and row["saves_per_1k"] == 15.0
        africa = next(g for g in perf["groups"]["continent"] if g["value"] == "Africa")
        assert africa["posts"] == 1 and africa["enough_data"] is False

    def test_recorded_posts_feed_the_existing_cast_analytics(self, db, writer):
        from app.services.culturetoon_analytics import compute_performance_summary
        out, cast = _approved(db, writer)
        self._post(out["id"])
        (bucket,) = compute_performance_summary(db(), cast.brand_id)
        assert bucket["post_count"] == 1 and bucket["avg_views"] == 2000

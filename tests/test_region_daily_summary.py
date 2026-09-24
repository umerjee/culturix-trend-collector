"""Daily country brief: input cleaning, validation, fallbacks, the cache skip,
the news collector, and the public endpoint."""
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collectors import news
from app.db import Base
from app.models.region_daily_summary import RegionDailySummary
from app.routers import world
from app.services import region_daily_summary as rds

DAY = date(2026, 9, 18)


def _row(title, platform="tiktok", likes=10, content=None):
    return SimpleNamespace(title=title, content=content, platform=platform, likes=likes)


def _inputs(**over):
    base = {
        "region": "FR", "day": DAY, "signal_count": 40,
        "topics": [{"title": f"Concrete topic number {i}", "platform": "tiktok", "likes": 5} for i in range(5)],
        "platforms": ["tiktok"], "themes": [], "events": [], "headlines": [],
        "baseline": {"enough": False, "days": 0, "recent_moods": []},
        "audience_matches": [],
    }
    base.update(over)
    return base


class TestCleaning:
    @pytest.mark.parametrize("raw", [
        "[Audio: original sound - someone by Someone]", "#fyp #foryou #viral", "@someone",
        "Main Page", "メインページ", "Special:Search", "ok", None, "", "https://x.co/abc #a",
    ])
    def test_noise_is_dropped(self, raw):
        assert rds.clean_title(raw) is None

    def test_hashtags_and_links_are_stripped_from_real_text(self):
        assert rds.clean_title("Kung Fu Panda is beautiful #kungfupanda #fyp https://t.co/x") == "Kung Fu Panda is beautiful"

    def test_topics_are_deduplicated_and_balanced_across_platforms(self):
        rows = [_row(f"Tiktok story number {i} here", "tiktok") for i in range(8)]
        rows += [_row("A youtube documentary about rivers", "youtube"), _row("A youtube documentary about rivers!", "youtube")]
        rows += [_row("Google trend about the election", "google_trends")]
        topics = rds.pick_topics(rows)
        platforms = [t["platform"] for t in topics]
        assert platforms.count("tiktok") == rds.PER_PLATFORM
        assert platforms.count("youtube") == 1  # near-duplicate title collapsed
        assert "google_trends" in platforms
        assert len(topics) <= rds.MAX_TOPICS

    def test_noise_rows_never_become_topics(self):
        assert rds.pick_topics([_row("[Audio: x by y]"), _row("#fyp")]) == []


class TestValidation:
    def test_clean_summary_passes_and_gets_a_final_period(self):
        assert rds.validate_summary("People engaged with Concrete topic number 1", _inputs()) == \
            "People engaged with Concrete topic number 1."

    def test_a_number_not_in_the_inputs_is_rejected(self):
        assert rds.validate_summary("A record 9000 people watched.", _inputs()) is None

    def test_a_number_from_the_inputs_is_allowed(self):
        inp = _inputs(events=[{"name": "Bastille Day", "category": "holiday", "date": "2026-09-21", "when": "in 3 days", "confirmed": True}])
        assert rds.validate_summary("Bastille Day is in 3 days.", inp) == "Bastille Day is in 3 days."

    @pytest.mark.parametrize("bad", [None, "", "   ", 42, "x" * 600, " ".join(["word"] * 95)])
    def test_unusable_text_is_rejected(self, bad):
        assert rds.validate_summary(bad, _inputs()) is None

    def test_feel_is_coerced_to_allowed_values(self):
        assert rds.parse_feel({"mood": "PLAYFUL", "sentiment": 5, "alignment": "diverged"}) == \
            {"mood": "playful", "sentiment": 2, "alignment": "diverged"}
        assert rds.parse_feel({"mood": "ecstatic", "sentiment": "x", "alignment": "??"}) == \
            {"mood": None, "sentiment": None, "alignment": "unknown"}


class TestPromptAndTemplate:
    def test_prompt_includes_news_and_history_but_not_the_comparison(self):
        inp = _inputs(
            headlines=[{"title": "Budget row in parliament", "source": "Le Monde"}],
            baseline={"enough": True, "days": 5, "volume_dir": "busier", "engagement_dir": "quieter",
                      "new_themes": ["Election"], "recent_moods": [{"date": "2026-09-17", "mood": "tense", "sentiment": -1}]},
        )
        prompt = rds.build_prompt(inp)
        assert "Budget row in parliament (Le Monde)" in prompt
        assert "Election" in prompt and "09-17: tense" in prompt
        assert "that sentence is added separately" in prompt
        assert "busier" not in prompt.split("Do NOT say how busy")[0].split("NEW VERSUS")[1]  # no volume verdict handed to the model

    def test_thin_history_tells_the_model_not_to_compare(self):
        prompt = rds.build_prompt(_inputs())
        assert "not available" in prompt  # no headlines
        assert "NEW VERSUS THE PAST WEEK: nothing notable" in prompt

    def test_no_calendar_instruction_present(self):
        assert "do NOT mention the calendar" in rds.build_prompt(_inputs())

    def test_template_uses_only_real_titles_and_events(self):
        inp = _inputs(events=[
            {"name": "Bastille Day", "category": "holiday", "date": "2026-09-18", "when": "today", "confirmed": True},
            {"name": "Election", "category": "political", "date": "2026-09-20", "when": "in 2 days", "confirmed": True},
        ])
        text = rds.template_summary(inp)
        assert text.startswith("Today in France: Bastille Day.")
        assert "Coming up: Election (in 2 days)." in text and "Concrete topic number 0" in text

    def test_calendar_only_template_omits_signals(self):
        inp = _inputs(events=[{"name": "Bastille Day", "category": "holiday", "date": "2026-09-18", "when": "today", "confirmed": True}])
        assert "Most engaged" not in rds.template_summary(inp, include_signals=False)

    def test_hash_changes_with_inputs_and_prompt_version(self, mocker):
        a = rds.inputs_hash(_inputs())
        assert a == rds.inputs_hash(_inputs())
        assert a != rds.inputs_hash(_inputs(headlines=[{"title": "New story", "source": None}]))
        mocker.patch.object(rds, "PROMPT_VERSION", rds.PROMPT_VERSION + 1)
        assert a != rds.inputs_hash(_inputs())


class TestComparison:
    @pytest.mark.parametrize("vol,eng,expected", [
        ("busier", "busier", "Activity was busier than usual."),
        ("quieter", "quieter", "Activity was quieter than usual."),
        ("quieter", "busier", "Fewer posts than usual, but more engagement per post."),
        ("busier", "quieter", "More posts than usual, but less engagement per post."),
        ("busier", "normal", "Post volume was busier than usual."),
        ("normal", "quieter", "Engagement per post was lower than usual."),
        ("normal", "busier", "Engagement per post was higher than usual."),
        ("normal", "normal", None),
        (None, None, None),
    ])
    def test_sentence_is_derived_from_the_measured_directions(self, vol, eng, expected):
        assert rds.compare_sentence({"enough": True, "volume_dir": vol, "engagement_dir": eng}) == expected

    def test_no_comparison_without_enough_history(self):
        assert rds.compare_sentence({"enough": False, "volume_dir": "busier", "engagement_dir": "busier"}) is None

    @pytest.mark.parametrize("ratio,expected", [(1.25, "busier"), (2.0, "busier"), (0.8, "quieter"), (0.3, "quieter"), (1.0, "normal"), (None, None)])
    def test_direction_thresholds(self, ratio, expected):
        assert rds.direction(ratio) == expected


class TestGenerate:
    @pytest.fixture
    def env(self, mocker):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        gather = mocker.patch.object(rds, "gather_inputs", return_value=_inputs())
        llm = mocker.patch.object(rds, "_write_with_llm", return_value=("People engaged with Topic.", {"mood": "playful", "sentiment": 1, "alignment": "diverged"}))
        fetcher = MagicMock(return_value=[{"title": "Headline", "source": "S"}])
        mocker.patch("app.services.region_daily_summary.datetime", wraps=datetime)
        return SimpleNamespace(session=session, gather=gather, llm=llm, fetcher=fetcher)

    def test_ai_path_stores_summary_feel_and_audit_inputs(self, env):
        row = rds.generate_region_summary(env.session, "fr", datetime.utcnow().date(), news_fetcher=env.fetcher)
        assert (row.region, row.source, row.summary) == ("FR", "ai", "People engaged with Topic.")
        assert (row.mood, row.sentiment, row.alignment) == ("playful", 1, "diverged")
        assert row.inputs_hash and row.topics and row.calendar == []
        env.session.commit.assert_called_once()

    def test_audience_matches_are_stored_when_there_is_enough_data(self, env):
        matches = [{"name": "Cosmic Curious", "description": "d", "content_angle": "a", "score": 0.5}]
        env.gather.return_value = _inputs(audience_matches=matches)
        row = rds.generate_region_summary(env.session, "FR", DAY, news_fetcher=env.fetcher)
        assert row.audience_matches == matches

    def test_audience_matches_are_empty_on_a_calendar_only_day(self, env):
        ev = {"name": "Bastille Day", "category": "holiday", "date": "2026-09-18", "when": "today", "confirmed": True}
        env.gather.return_value = _inputs(signal_count=3, topics=[], events=[ev],
                                          audience_matches=[{"name": "Should not appear", "description": "", "content_angle": None, "score": 0.9}])
        row = rds.generate_region_summary(env.session, "FR", DAY, news_fetcher=env.fetcher)
        assert row.audience_matches == []

    def test_news_is_fetched_only_for_today(self, env):
        rds.generate_region_summary(env.session, "FR", date(2020, 1, 1), news_fetcher=env.fetcher)
        env.fetcher.assert_not_called()
        rds.generate_region_summary(env.session, "FR", datetime.utcnow().date(), news_fetcher=env.fetcher)
        env.fetcher.assert_called_once()

    def test_the_comparison_sentence_is_appended_and_matches_the_label(self, env):
        base = {"enough": True, "days": 5, "volume_dir": "quieter", "engagement_dir": "busier", "new_themes": [], "recent_moods": []}
        env.gather.return_value = _inputs(baseline=base)
        row = rds.generate_region_summary(env.session, "FR", DAY, news_fetcher=env.fetcher)
        assert row.summary.endswith("Fewer posts than usual, but more engagement per post.")
        assert world._vs_usual_label(row.baseline) == "quieter"

    def test_llm_failure_falls_back_to_the_template(self, env):
        env.llm.return_value = None
        row = rds.generate_region_summary(env.session, "FR", DAY, news_fetcher=env.fetcher)
        assert row.source == "template" and row.summary.startswith("Most engaged with:") and row.mood is None

    def test_thin_data_without_events_says_nothing(self, env):
        env.gather.return_value = _inputs(signal_count=3, topics=[])
        assert rds.generate_region_summary(env.session, "FR", DAY, news_fetcher=env.fetcher) is None
        env.llm.assert_not_called()

    def test_thin_data_with_an_event_gets_a_calendar_only_line_and_no_llm(self, env):
        ev = {"name": "Bastille Day", "category": "holiday", "date": "2026-09-18", "when": "today", "confirmed": True}
        env.gather.return_value = _inputs(signal_count=3, topics=[], events=[ev])
        row = rds.generate_region_summary(env.session, "FR", DAY, news_fetcher=env.fetcher)
        assert row.source == "calendar" and "Bastille Day" in row.summary
        env.llm.assert_not_called()

    def test_enough_signals_but_all_noise_is_not_summarized(self, env):
        env.gather.return_value = _inputs(signal_count=80, topics=[])
        assert rds.generate_region_summary(env.session, "FR", DAY, news_fetcher=env.fetcher) is None

    def test_unchanged_inputs_skip_the_llm(self, env):
        existing = SimpleNamespace(inputs_hash=rds.inputs_hash(_inputs()), source="ai")
        env.session.query.return_value.filter_by.return_value.first.return_value = existing
        row = rds.generate_region_summary(env.session, "FR", DAY, force=True, news_fetcher=env.fetcher)
        assert row is existing
        env.llm.assert_not_called()

    def test_a_cached_template_is_retried_even_when_inputs_are_unchanged(self, env):
        existing = SimpleNamespace(inputs_hash=rds.inputs_hash(_inputs()), source="template")
        env.session.query.return_value.filter_by.return_value.first.return_value = existing
        rds.generate_region_summary(env.session, "FR", DAY, force=True, news_fetcher=env.fetcher)
        env.llm.assert_called_once()

    def test_without_force_an_existing_row_is_returned_untouched(self, env):
        existing = SimpleNamespace(inputs_hash="x", source="ai")
        env.session.query.return_value.filter_by.return_value.first.return_value = existing
        assert rds.generate_region_summary(env.session, "FR", DAY, news_fetcher=env.fetcher) is existing
        env.gather.assert_not_called()

    def test_one_failing_region_does_not_stop_the_batch(self, mocker):
        mocker.patch.object(rds, "regions_to_summarize", return_value=["AA", "BB"])
        mocker.patch.object(rds, "generate_region_summary",
                            side_effect=[RuntimeError("boom"), SimpleNamespace(source="ai")])
        counts = rds.generate_all_summaries(MagicMock(), DAY)
        assert counts["failed"] == 1 and counts["ai"] == 1


class TestNewsCollector:
    RSS = b"""<rss><channel>
      <item><title>Budget row deepens - Le Monde</title><source>Le Monde</source></item>
      <item><title>  Football   squad named </title><source>L'Equipe</source></item>
      <item><title></title></item>
    </channel></rss>"""

    def test_parses_titles_strips_publisher_suffix_and_skips_empty(self, mocker):
        mocker.patch("httpx.get", return_value=MagicMock(content=self.RSS, raise_for_status=lambda: None))
        items = news._fetch("fr", "FR", "fr")
        assert items == [{"title": "Budget row deepens", "source": "Le Monde"},
                         {"title": "Football squad named", "source": "L'Equipe"}]

    def test_never_raises_and_returns_empty_on_failure(self, mocker):
        mocker.patch("httpx.get", side_effect=RuntimeError("down"))
        assert news.fetch_country_headlines("FR") == []

    def test_bad_region_codes_return_empty_without_a_request(self, mocker):
        get = mocker.patch("httpx.get")
        assert news.fetch_country_headlines("") == [] and news.fetch_country_headlines("FRA") == []
        get.assert_not_called()

    def test_a_country_without_a_real_edition_never_gets_the_english_us_fallback(self, mocker):
        get = mocker.patch("httpx.get", side_effect=RuntimeError("down"))
        news.fetch_country_headlines("CL")  # no local edition mapped, no English edition
        get.assert_not_called()

    def test_english_fallback_is_used_for_english_edition_countries(self, mocker):
        many = b"<rss><channel>" + b"".join(b"<item><title>Story %d</title></item>" % i for i in range(6)) + b"</channel></rss>"
        get = mocker.patch("httpx.get", return_value=MagicMock(content=many, raise_for_status=lambda: None))
        assert len(news.fetch_country_headlines("NG")) == 6
        assert get.call_args.kwargs["params"]["ceid"] == "NG:en"


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[RegionDailySummary.__table__])
    Session = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", Session)
    from app.translation.service import TranslationResult
    mocker.patch("app.translation.translate", side_effect=lambda text, target, **kw: TranslationResult(
        text=f"[{target}] {text}", target=target, ok=True, translated=True))
    return Session


def _store(db, region="FR", day=DAY, **over):
    s = db()
    s.add(RegionDailySummary(region=region, summary_date=day, summary=over.pop("summary", "A brief."),
                             source="ai", signal_count=40, platforms=["tiktok"], news=["SECRET HEADLINE"],
                             calendar=[{"name": "Bastille Day"}], mood="playful", sentiment=1,
                             alignment="diverged", baseline={"volume_dir": "busier"},
                             audience_matches=over.pop("audience_matches", [{"name": "Reality TV Stan", "description": "d", "content_angle": "a", "score": 0.6}]), **over))
    s.commit()
    s.close()


def _persona(mocker, name, description="d", suggestions="Do X. Then Y.", embedding=None, status="active"):
    return SimpleNamespace(name=name, description=description, content_suggestions=suggestions,
                           relevance_embedding=embedding, status=status)


class TestPersonaMatches:
    TOPICS = [{"title": "The new season of a hit reality show"}, {"title": "A viral cooking trend"}]

    def test_matches_above_the_threshold_are_returned_ranked_by_score(self, mocker):
        mocker.patch("app.embeddings.embed_text", return_value=[1.0, 0.0])
        close = _persona(mocker, "Reality TV Stan", embedding=[0.9, 0.1])
        far = _persona(mocker, "Weak Match", embedding=[0.1, 0.9])
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [far, close]
        result = rds.top_persona_matches(session, self.TOPICS, [])
        assert [m["name"] for m in result] == ["Reality TV Stan"]  # "far" scores below PERSONA_MATCH_MIN_SCORE
        assert result[0]["score"] > rds.PERSONA_MATCH_MIN_SCORE

    def test_the_content_angle_is_the_first_sentence_only(self, mocker):
        mocker.patch("app.embeddings.embed_text", return_value=[1.0, 0.0])
        p = _persona(mocker, "P", suggestions="Show behind-the-scenes footage. Then do a reaction video. And more.", embedding=[1.0, 0.0])
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [p]
        assert rds.top_persona_matches(session, self.TOPICS, [])[0]["content_angle"] == "Show behind-the-scenes footage"

    def test_a_persona_with_no_suggestions_gets_no_angle(self, mocker):
        mocker.patch("app.embeddings.embed_text", return_value=[1.0, 0.0])
        p = _persona(mocker, "P", suggestions=None, embedding=[1.0, 0.0])
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [p]
        assert rds.top_persona_matches(session, self.TOPICS, [])[0]["content_angle"] is None

    def test_never_the_models_own_words_only_stored_persona_text(self, mocker):
        llm = mocker.patch("app.services.culturix_ingestion._call_llm_json")
        mocker.patch("app.embeddings.embed_text", return_value=[1.0, 0.0])
        p = _persona(mocker, "P", description="Exact stored description.", embedding=[1.0, 0.0])
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [p]
        result = rds.top_persona_matches(session, self.TOPICS, [])
        assert result[0]["description"] == "Exact stored description."
        llm.assert_not_called()

    def test_capped_at_max_matches(self, mocker):
        mocker.patch("app.embeddings.embed_text", return_value=[1.0, 0.0])
        personas = [_persona(mocker, f"P{i}", embedding=[1.0, 0.0]) for i in range(10)]
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = personas
        assert len(rds.top_persona_matches(session, self.TOPICS, [])) == rds.MAX_PERSONA_MATCHES

    def test_falls_back_to_themes_when_there_are_no_clean_topics(self, mocker):
        embed = mocker.patch("app.embeddings.embed_text", return_value=[1.0, 0.0])
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []
        rds.top_persona_matches(session, [], ["A real detected theme"])
        assert embed.call_args.args[0] == "A real detected theme"

    def test_nothing_to_embed_is_empty_without_calling_the_embedder(self, mocker):
        embed = mocker.patch("app.embeddings.embed_text")
        session = MagicMock()
        assert rds.top_persona_matches(session, [], []) == []
        embed.assert_not_called()

    def test_a_failed_embedding_call_is_empty_not_an_exception(self, mocker):
        mocker.patch("app.embeddings.embed_text", side_effect=RuntimeError("down"))
        session = MagicMock()
        assert rds.top_persona_matches(session, self.TOPICS, []) == []

    def test_an_empty_embedding_is_empty(self, mocker):
        mocker.patch("app.embeddings.embed_text", return_value=[])
        session = MagicMock()
        assert rds.top_persona_matches(session, self.TOPICS, []) == []

    def test_dormant_personas_and_ones_with_no_cached_embedding_are_excluded_by_the_query(self, mocker):
        mocker.patch("app.embeddings.embed_text", return_value=[1.0, 0.0])
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []
        rds.top_persona_matches(session, self.TOPICS, [])
        filter_args = session.query.return_value.filter.call_args
        assert filter_args is not None


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        assert rds._cosine_similarity([1.0, 2.0], [1.0, 2.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert rds._cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    @pytest.mark.parametrize("a,b", [([], [1.0]), ([1.0], []), ([1.0, 2.0], [1.0]), (None, [1.0])])
    def test_mismatched_or_empty_vectors_score_zero(self, a, b):
        assert rds._cosine_similarity(a, b) == 0.0


class TestSummaryEndpoint:
    def test_returns_the_latest_summary_and_never_exposes_raw_headlines(self, db):
        _store(db, day=date(2026, 9, 10), summary="Older.")
        _store(db, day=date(2026, 9, 17), summary="Newer.")
        out = world.get_region_summary("fr")
        assert out["summary"] == "Newer." and out["date"] == "2026-09-17"
        assert (out["mood"], out["alignment"], out["vs_usual"]) == ("playful", "diverged", "busier")
        assert "SECRET HEADLINE" not in str(out) and "news" not in out

    def test_a_specific_date(self, db):
        _store(db, day=date(2026, 9, 10), summary="Older.")
        _store(db, day=date(2026, 9, 17), summary="Newer.")
        assert world.get_region_summary("FR", date="2026-09-10")["summary"] == "Older."

    def test_no_summary_is_a_normal_empty_state(self, db):
        out = world.get_region_summary("JP")
        assert out["summary"] is None and out["region_name"] == "Japan" and out["calendar"] == []
        assert out["audience_matches"] == []
        # facts are static reference data, independent of whether a daily summary exists.
        assert out["facts"]["capital"] == "Tokyo"

    def test_facts_are_included_alongside_a_real_summary(self, db):
        _store(db)
        assert world.get_region_summary("FR", date="2026-09-18")["facts"]["currency_code"] == "EUR"

    def test_a_region_with_no_facts_on_file_returns_none_not_an_error(self, db):
        assert world.get_region_summary("MC")["facts"] is None

    def test_audience_matches_are_returned(self, db):
        _store(db)
        out = world.get_region_summary("FR", date="2026-09-18")
        assert out["audience_matches"] == [{"name": "Reality TV Stan", "description": "d", "content_angle": "a", "score": 0.6}]

    def test_future_summaries_are_not_returned_as_latest(self, db):
        _store(db, day=date(2099, 1, 1), summary="From the future.")
        assert world.get_region_summary("FR")["summary"] is None

    def test_translation_is_applied(self, db):
        _store(db)
        assert world.get_region_summary("FR", date="2026-09-18", lang="fr")["summary"] == "[fr] A brief."

    def test_unsupported_language_falls_back_to_english(self, db):
        _store(db)
        assert world.get_region_summary("FR", date="2026-09-18", lang="xx")["summary"] == "A brief."

    @pytest.mark.parametrize("bad", ["", "F", "FRA", "12", "F1"])
    def test_invalid_region_codes_are_rejected(self, db, bad):
        with pytest.raises(world.HTTPException) as exc:
            world.get_region_summary(bad)
        assert exc.value.status_code == 400

    def test_invalid_date_is_a_400(self, db):
        with pytest.raises(world.HTTPException) as exc:
            world.get_region_summary("FR", date="not-a-date")
        assert exc.value.status_code == 400

    def test_vs_usual_label(self):
        assert world._vs_usual_label({"volume_dir": "quieter"}) == "quieter"
        assert world._vs_usual_label({"volume_dir": "normal"}) == "normal"
        assert world._vs_usual_label({"enough": False}) is None and world._vs_usual_label(None) is None

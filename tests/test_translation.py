"""Shared translation module: languages, the Google engine's protections, the
cache, honest failures, the compatibility wrappers, and the World digest."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import language
from app.db import Base
from app.models.cluster import Cluster
from app.models.translation_cache import TranslationCache
from app.models.trend import Trend
from app.routers import world
from app.translation import engines, service
from app.translation.engines import EngineError, EngineUnavailable, GoogleEngine
from app.translation.languages import engine_code, normalize_language


class TestLanguages:
    @pytest.mark.parametrize("raw,expected", [
        ("EN", "en"), ("fr", "fr"), ("pt-BR", "pt"), ("iw", "he"), ("zh", "zh-CN"), ("zh-tw", "zh-TW"),
        ("ZH-CN", "zh-CN"), (" ja ", "ja"), ("xx", None), ("", None), (None, None), ("klingon", None),
    ])
    def test_normalize(self, raw, expected):
        assert normalize_language(raw) == expected

    def test_google_calls_hebrew_iw(self):
        # verified live: "he" is rejected by the library, "iw" works
        assert engine_code("google", "he") == "iw"
        assert engine_code("google", "fr") == "fr"


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(mocker):
    c = FakeClock()
    mocker.patch("app.translation.engines.time.monotonic", c.monotonic)
    mocker.patch("app.translation.engines.time.sleep", c.sleep)
    return c


def _google(mocker, translate):
    """A GoogleEngine whose HTTP client is replaced by `translate(text) -> str`."""
    engine = GoogleEngine()
    client = SimpleNamespace(translate=translate)
    mocker.patch.object(engine, "_client", return_value=client)
    return engine


class TestGoogleEngine:
    def test_several_short_texts_share_one_request(self, mocker, clock):
        calls = []
        engine = _google(mocker, lambda t: calls.append(t) or t.upper())
        assert engine.translate_batch(["a b", "c d", "e f"], "fr") == ["A B", "C D", "E F"]
        assert calls == ["a b\nc d\ne f"]

    def test_misaligned_batch_falls_back_to_one_request_per_text(self, mocker, clock):
        calls = []

        def merge_lines(text):
            calls.append(text)
            return text.replace("\n", " ").upper()  # Google merged the lines

        engine = _google(mocker, merge_lines)
        assert engine.translate_batch(["aa", "bb"], "fr") == ["AA", "BB"]
        assert calls == ["aa\nbb", "aa", "bb"]

    def test_internal_newlines_cannot_corrupt_the_batch_alignment(self, mocker, clock):
        calls = []
        engine = _google(mocker, lambda t: calls.append(t) or t)
        engine.translate_batch(["two\nlines", "one"], "fr")
        assert calls[0] == "two lines\none"

    def test_batches_respect_the_request_size_limit(self):
        groups = GoogleEngine._group(["x" * 3000, "y" * 3000, "z" * 100])
        assert groups == [[0], [1, 2]]

    def test_a_text_over_the_limit_is_split_and_rejoined(self, mocker, clock):
        calls = []
        engine = _google(mocker, lambda t: calls.append(t) or t)
        text = "\n".join(["line " + "w" * 1500] * 4)
        assert engine.translate_batch([text], "fr") == [text]
        assert len(calls) == 2 and all(len(c) <= engines.MAX_REQUEST_CHARS for c in calls)

    def test_calls_are_throttled(self, mocker, clock):
        engine = _google(mocker, lambda t: t)
        engine.translate_batch(["one text"], "fr")
        engine.translate_batch(["two text"], "fr")
        assert clock.slept and clock.slept[0] == pytest.approx(GoogleEngine.MIN_GAP_SECONDS)

    def test_rate_limit_backs_off_then_succeeds(self, mocker, clock):
        outcomes = [Exception("Server Error: You made too many requests"), "bonjour"]

        def flaky(text):
            out = outcomes.pop(0)
            if isinstance(out, Exception):
                raise out
            return out

        engine = _google(mocker, flaky)
        assert engine.translate_batch(["hello"], "fr") == ["bonjour"]
        assert 2.0 in clock.slept

    def test_repeated_rate_limiting_opens_the_breaker_and_fails_fast(self, mocker, clock):
        calls = []

        def limited(text):
            calls.append(text)
            raise Exception("too many requests")

        engine = _google(mocker, limited)
        with pytest.raises(EngineUnavailable):
            engine.translate_batch(["hello"], "fr")
        made = len(calls)
        with pytest.raises(EngineUnavailable):  # breaker open: no request is made at all
            engine.translate_batch(["hello again"], "fr")
        assert len(calls) == made

    def test_breaker_closes_after_the_cooldown(self, mocker, clock):
        state = {"fail": True}

        def flaky(text):
            if state["fail"]:
                raise Exception("too many requests")
            return "ok"

        engine = _google(mocker, flaky)
        with pytest.raises(EngineUnavailable):
            engine.translate_batch(["hello"], "fr")
        state["fail"] = False
        clock.now += GoogleEngine.BREAKER_COOLDOWN_SECONDS + 1
        assert engine.translate_batch(["hello"], "fr") == ["ok"]

    def test_other_errors_are_engine_errors_and_do_not_trip_the_breaker(self, mocker, clock):
        engine = _google(mocker, lambda t: (_ for _ in ()).throw(Exception("No support for the provided language")))
        with pytest.raises(EngineError) as exc:
            engine.translate_batch(["hello"], "fr")
        assert not isinstance(exc.value, EngineUnavailable)

    def test_unknown_engine_is_rejected(self):
        with pytest.raises(ValueError):
            engines.get_engine("nope")


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[TranslationCache.__table__, Trend.__table__, Cluster.__table__])
    Session = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", Session)
    return Session


class FakeEngine:
    name = "google"

    def __init__(self, fn=None):
        self.calls = []
        self.fn = fn or (lambda t: f"<{t}>")

    def translate_batch(self, texts, target, source="auto"):
        self.calls.append(list(texts))
        return [self.fn(t) for t in texts]


@pytest.fixture
def fake(mocker, db):
    engine = FakeEngine()
    mocker.patch("app.translation.service.get_engine", return_value=engine)
    return engine


class TestService:
    def test_translates_and_reports_it(self, fake):
        r = service.translate("Bonjour tout le monde", "en")
        assert (r.text, r.ok, r.translated, r.cached, r.engine) == ("<Bonjour tout le monde>", True, True, False, "google")

    def test_second_call_is_served_from_the_cache_with_no_engine_call(self, fake):
        service.translate("Bonjour tout le monde", "en")
        again = service.translate("Bonjour tout le monde", "en")
        assert again.cached and again.text == "<Bonjour tout le monde>"
        assert len(fake.calls) == 1

    def test_cache_is_per_target_language(self, fake):
        service.translate("Bonjour tout le monde", "en")
        service.translate("Bonjour tout le monde", "de")
        assert len(fake.calls) == 2

    def test_only_the_hash_of_the_source_is_stored(self, fake, db):
        service.translate("A secret sentence here", "fr")
        row = db().query(TranslationCache).one()
        assert row.text_hash == service._hash("A secret sentence here") and row.source_chars == 22
        assert not hasattr(row, "source_text")

    def test_many_deduplicates_and_keeps_order(self, fake):
        out = service.translate_many(["alpha text", "beta text", "alpha text"], "fr")
        assert [r.text for r in out] == ["<alpha text>", "<beta text>", "<alpha text>"]
        assert fake.calls == [["alpha text", "beta text"]]

    def test_many_sends_only_cache_misses(self, fake):
        service.translate("alpha text", "fr")
        fake.calls.clear()
        out = service.translate_many(["alpha text", "gamma text"], "fr")
        assert out[0].cached and not out[1].cached
        assert fake.calls == [["gamma text"]]

    @pytest.mark.parametrize("text", ["", "   ", "12345", "https://example.com/x", "😂😂", "!!!"])
    def test_nothing_translatable_makes_no_request(self, fake, text):
        r = service.translate(text, "fr")
        assert (r.text, r.ok, r.translated) == (text, True, False)
        assert fake.calls == []

    def test_text_already_in_the_target_language_makes_no_request(self, fake, mocker):
        mocker.patch("app.translation.service.detect_language", return_value="en")
        r = service.translate("This sentence is already written in English, plainly.", "en")
        assert not r.translated and r.ok and fake.calls == []

    def test_short_text_is_never_skipped_on_a_guess(self, fake, mocker):
        detect = mocker.patch("app.translation.service.detect_language", return_value="en")
        service.translate("Hola amigo", "en")  # short: detection is not trusted
        detect.assert_not_called()
        assert len(fake.calls) == 1

    def test_explicit_same_source_language_skips(self, fake):
        assert not service.translate("Bonjour", "fr", source="fr").translated
        assert fake.calls == []

    def test_unsupported_target_is_reported_not_hidden(self, fake):
        r = service.translate("Bonjour tout le monde", "xx")
        assert not r.ok and "Unsupported" in r.error and r.text == "Bonjour tout le monde"

    def test_engine_failure_returns_the_original_flagged_and_is_not_cached(self, mocker, db):
        boom = FakeEngine()
        boom.translate_batch = MagicMock(side_effect=EngineUnavailable("cooling down"))
        mocker.patch("app.translation.service.get_engine", return_value=boom)
        r = service.translate("Bonjour tout le monde", "en")
        assert (r.text, r.ok, r.translated) == ("Bonjour tout le monde", False, False)
        assert "cooling down" in r.error
        assert db().query(TranslationCache).count() == 0

    def test_a_crashing_engine_never_raises_into_a_page_view(self, mocker, db):
        boom = FakeEngine()
        boom.translate_batch = MagicMock(side_effect=RuntimeError("bug"))
        mocker.patch("app.translation.service.get_engine", return_value=boom)
        r = service.translate("Bonjour tout le monde", "en")
        assert not r.ok and r.text == "Bonjour tout le monde"

    def test_empty_translation_is_a_failure(self, mocker, db):
        mocker.patch("app.translation.service.get_engine", return_value=FakeEngine(fn=lambda t: "  "))
        r = service.translate("Bonjour tout le monde", "en")
        assert not r.ok and r.error == "Empty translation"
        assert db().query(TranslationCache).count() == 0

    def test_cache_outage_degrades_to_translating_without_it(self, mocker):
        engine = FakeEngine()
        mocker.patch("app.translation.service.get_engine", return_value=engine)
        mocker.patch("app.db.SessionLocal", side_effect=RuntimeError("db down"))
        r = service.translate("Bonjour tout le monde", "en")
        assert r.ok and r.translated and r.text == "<Bonjour tout le monde>"

    def test_partial_failure_of_one_call_marks_every_text_in_it(self, mocker, db):
        boom = FakeEngine()
        boom.translate_batch = MagicMock(side_effect=EngineUnavailable("x"))
        mocker.patch("app.translation.service.get_engine", return_value=boom)
        out = service.translate_many(["one thing", "two things"], "fr")
        assert [r.ok for r in out] == [False, False] and [r.text for r in out] == ["one thing", "two things"]


class TestCompatibilityWrappers:
    def test_translate_to_english(self, fake):
        assert language.translate_to_english("Bonjour tout le monde") == "<Bonjour tout le monde>"

    def test_english_and_french_are_kept_by_the_pipeline_rule(self, fake):
        assert language.translate_to_english_if_needed("Salut", "fr") == "Salut"
        assert language.translate_to_english_if_needed("Hola amigo", "es") == "<Hola amigo>"
        assert fake.calls == [["Hola amigo"]]

    def test_translate_text_now_supports_any_registered_language(self, fake):
        assert language.translate_text("Hello there friend", "de") == "<Hello there friend>"
        assert language.translate_text("Hello there friend", "ja") == "<Hello there friend>"

    def test_failure_keeps_the_old_return_the_original_contract(self, mocker, db):
        boom = FakeEngine()
        boom.translate_batch = MagicMock(side_effect=EngineUnavailable("x"))
        mocker.patch("app.translation.service.get_engine", return_value=boom)
        assert language.translate_text("Hello there friend", "de") == "Hello there friend"

    def test_empty_input(self, fake):
        assert language.translate_text("", "de") == "" and language.translate_to_english("  ") == "  "


class TestWorldDigest:
    def _seed(self, db):
        s = db()
        cluster = Cluster(label=1, theme="Election night", summary="Voters react", momentum="up")
        s.add(cluster)
        s.commit()
        for i in range(3):
            s.add(Trend(platform="tiktok", title=f"Post number {i} about the vote", content="c", likes=100 - i,
                        region="FR", cluster_id=cluster.id))
        s.commit()
        s.close()

    def test_the_whole_digest_is_translated_in_one_batched_call(self, db, mocker):
        self._seed(db)
        spy = mocker.patch("app.translation.translate_many", side_effect=lambda texts, lang: [
            SimpleNamespace(text=f"[{lang}] {t}", ok=True) for t in texts])
        out = world.list_world_trend_digest(region="FR", lang="de")
        assert spy.call_count == 1
        group = out["groups"][0]
        assert group["title"] == "[de] Election night" and group["summary"] == "[de] Voters react"
        assert all(sig["title"].startswith("[de] ") for sig in group["signals"])
        assert out["translation"] == {"lang": "de", "failed": 0}

    def test_failures_are_counted_and_the_original_text_is_shown(self, db, mocker):
        self._seed(db)
        mocker.patch("app.translation.translate_many", side_effect=lambda texts, lang: [
            SimpleNamespace(text=t, ok=False) for t in texts])
        out = world.list_world_trend_digest(region="FR", lang="fr")
        assert out["groups"][0]["title"] == "Election night"
        assert out["translation"]["failed"] > 0

    def test_unsupported_language_falls_back_to_english(self, db, mocker):
        self._seed(db)
        spy = mocker.patch("app.translation.translate_many", side_effect=lambda texts, lang: [
            SimpleNamespace(text=t, ok=True) for t in texts])
        out = world.list_world_trend_digest(region="FR", lang="klingon")
        assert out["translation"]["lang"] == "en" and spy.call_args.args[1] == "en"


class TestPipelineTranslatorNode:
    """The ingestion node must never mark a row translated when translation failed."""

    @staticmethod
    def _row(text, lang_hint=None):
        return SimpleNamespace(content=text, title=None, language=None, translated_content=None, lang_hint=lang_hint)

    @staticmethod
    def _detect(text):
        return "fr" if text.startswith("FR:") else "en" if text.startswith("EN:") else "de"

    def _run(self, rows, translate_many):
        from app.pipeline.nodes.translator import translate_rows
        return translate_rows(rows, translate_many, self._detect, {"en", "fr", "unknown"})

    def test_kept_languages_are_copied_and_others_translated_in_one_batch(self):
        rows = [self._row("EN: hello"), self._row("FR: salut"), self._row("Guten Tag"), self._row("Danke sehr")]
        calls = []

        def many(texts, target):
            calls.append((list(texts), target))
            return [SimpleNamespace(text=f"<{t}>", ok=True, cached=False) for t in texts]

        counts = self._run(rows, many)
        assert calls == [(["Guten Tag", "Danke sehr"], "en")]  # ONE call, only the non-kept rows
        assert [r.translated_content for r in rows] == ["EN: hello", "FR: salut", "<Guten Tag>", "<Danke sehr>"]
        assert counts == {"translated": 2, "kept": 2, "failed": 0, "cached": 0}

    def test_a_failed_translation_leaves_the_row_empty_so_it_is_retried(self):
        rows = [self._row("Guten Tag"), self._row("Danke sehr")]
        many = lambda texts, target: [
            SimpleNamespace(text="<ok>", ok=True, cached=True), SimpleNamespace(text=texts[1], ok=False, cached=False)]
        counts = self._run(rows, many)
        assert rows[0].translated_content == "<ok>"
        assert rows[1].translated_content is None  # NOT the untranslated German text
        assert counts["failed"] == 1 and counts["cached"] == 1

    def test_blank_rows_are_skipped_and_nothing_pending_makes_no_call(self):
        rows = [self._row("   "), self._row("EN: fine")]
        many = MagicMock()
        counts = self._run(rows, many)
        many.assert_not_called()
        assert rows[0].translated_content is None and counts["kept"] == 1

    def test_the_node_reports_untranslated_rows_in_pipeline_errors(self, db, mocker):
        s = db()
        s.add(Trend(platform="tiktok", content="Guten Tag", region="DE"))
        s.commit()
        s.close()
        mocker.patch("app.language.detect_language", return_value="de")
        mocker.patch("app.translation.translate_many", side_effect=lambda texts, target: [
            SimpleNamespace(text=t, ok=False, cached=False) for t in texts])
        from app.pipeline.nodes.translator import translate_signals
        state = translate_signals({"errors": []})
        assert any("left untranslated" in e for e in state["errors"])
        assert db().query(Trend).one().translated_content is None

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.integration_health import IntegrationHealth
from app.integration_health import check_edge_tts, check_twitter_proxy, run_all_health_checks


class TestCheckEdgeTts:
    def test_healthy_when_synthesize_returns_audio_bytes(self, mocker):
        mock_result = mocker.Mock(asset_bytes=b"fake-audio-bytes")
        mocker.patch("app.media.voice.EdgeTTSProvider.synthesize", return_value=mock_result)

        status, error = check_edge_tts()

        assert status == "healthy"
        assert error is None

    def test_unhealthy_when_synthesize_raises(self, mocker):
        mocker.patch("app.media.voice.EdgeTTSProvider.synthesize", side_effect=RuntimeError("edge-tts broke"))

        status, error = check_edge_tts()

        assert status == "unhealthy"
        assert "edge-tts broke" in error

    def test_unhealthy_when_no_audio_bytes_returned(self, mocker):
        mock_result = mocker.Mock(asset_bytes=b"")
        mocker.patch("app.media.voice.EdgeTTSProvider.synthesize", return_value=mock_result)

        status, error = check_edge_tts()

        assert status == "unhealthy"
        assert "no audio" in error


class TestCheckTwitterProxy:
    def test_healthy_on_200_with_body(self, mocker):
        resp = mocker.Mock(status_code=200, text="1. [Some Trend](url)")
        mocker.patch("httpx.get", return_value=resp)

        status, error = check_twitter_proxy()

        assert status == "healthy"
        assert error is None

    def test_unhealthy_on_non_200(self, mocker):
        resp = mocker.Mock(status_code=503, text="")
        mocker.patch("httpx.get", return_value=resp)

        status, error = check_twitter_proxy()

        assert status == "unhealthy"
        assert "503" in error

    def test_unhealthy_on_empty_body(self, mocker):
        resp = mocker.Mock(status_code=200, text="   ")
        mocker.patch("httpx.get", return_value=resp)

        status, error = check_twitter_proxy()

        assert status == "unhealthy"
        assert "empty" in error

    def test_unhealthy_on_request_exception(self, mocker):
        mocker.patch("httpx.get", side_effect=Exception("connection reset"))

        status, error = check_twitter_proxy()

        assert status == "unhealthy"
        assert "connection reset" in error


@pytest.fixture
def health_db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[IntegrationHealth.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestRunAllHealthChecks:
    def test_persists_one_row_per_integration(self, health_db, mocker):
        # _CHECKS holds direct function references bound at module load —
        # patching the check_* names by string doesn't change what's already
        # stored in the dict, so the dict itself must be patched instead.
        mocker.patch.dict(
            "app.integration_health._CHECKS",
            {
                "edge_tts": lambda: ("healthy", None),
                "twitter_proxy": lambda: ("unhealthy", "boom"),
            },
            clear=True,
        )

        results = run_all_health_checks()

        assert results == {"edge_tts": "healthy", "twitter_proxy": "unhealthy"}

        session = health_db()
        rows = session.query(IntegrationHealth).all()
        session.close()
        assert len(rows) == 2
        by_name = {r.integration_name: r for r in rows}
        assert by_name["edge_tts"].status == "healthy"
        assert by_name["twitter_proxy"].status == "unhealthy"
        assert by_name["twitter_proxy"].error == "boom"

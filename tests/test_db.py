"""Regression coverage for a real incident (2026-09-25): a bare "postgresql://" URL left
SQLAlchemy's dialect resolution to chance, and a fresh `pip install` in CI (SQLAlchemy
unpinned at the time) resolved it to the psycopg (v3) dialect instead of psycopg2 — which
isn't installed, only psycopg2-binary is. Every test module importing app.db failed with
"No module named 'psycopg'" (41 collection errors). Production's real Railway DATABASE_URL
uses the same bare scheme, so it was equally exposed on its next fresh dependency install.
"""
import pytest

from app.db import _force_psycopg2_driver


class TestForcePsycopg2Driver:
    def test_a_bare_postgresql_url_gets_the_driver_forced(self):
        assert _force_psycopg2_driver("postgresql://user:pw@host:5432/db") == \
            "postgresql+psycopg2://user:pw@host:5432/db"

    @pytest.mark.parametrize("url", [
        "postgresql+psycopg2://user:pw@host:5432/db",
        "postgresql+psycopg://user:pw@host:5432/db",  # an explicit choice is left alone, not overridden
        "sqlite:///:memory:",
    ])
    def test_a_url_with_an_explicit_driver_or_non_postgres_scheme_is_left_alone(self, url):
        assert _force_psycopg2_driver(url) == url

    def test_none_is_left_alone(self):
        assert _force_psycopg2_driver(None) is None

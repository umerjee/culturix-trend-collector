"""Reference photos as each scene's opening frame: only public-domain images, copied to our storage."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.toon_background import ToonBackground
from app.services import world_references as wr


class TestLicense:
    @pytest.mark.parametrize("license_name,terms,ok", [
        ("Public domain", "", True),
        ("PD-USGov", "", True),
        ("PD US Navy", "", True),
        ("", "Public domain", True),
        ("CC BY-SA 4.0", "Creative Commons Attribution-Share Alike 4.0", False),
        ("CC0", "", False),
        ("GFDL", "", False),
        ("Attribution", "Public domain photo, attribution required", False),
        ("", "", False),
        ("Unknown", "", False),
    ])
    def test_only_public_domain_passes(self, license_name, terms, ok):
        assert wr.is_public_domain(license_name, terms) is ok


def _page(title, license_name="Public domain", width=2000, mime="image/jpeg", thumb="https://up/x.jpg", desc="<p>A <b>photo</b></p>"):
    return {"title": title, "imageinfo": [{
        "width": width, "height": 1500, "mime": mime, "thumburl": thumb, "descriptionurl": f"https://commons/{title}",
        "extmetadata": {"LicenseShortName": {"value": license_name}, "UsageTerms": {"value": license_name},
                        "Credit": {"value": "<a>US Navy</a>"}, "ImageDescription": {"value": desc}}}]}


def _mock_commons(mocker, titles, pages):
    def get(url, params=None, headers=None, **kw):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if params.get("list") == "search":
            resp.json.return_value = {"query": {"search": [{"title": t} for t in titles]}}
        else:
            resp.json.return_value = {"query": {"pages": {str(i): p for i, p in enumerate(pages)}}}
        return resp
    return mocker.patch("httpx.get", side_effect=get)


class TestFind:
    def test_keeps_public_domain_images_only_in_search_order(self, mocker):
        _mock_commons(mocker, ["File:B.jpg", "File:A.jpg", "File:C.jpg"], [
            _page("File:A.jpg"), _page("File:B.jpg"), _page("File:C.jpg", license_name="CC BY-SA 4.0")])
        results = wr.find_public_domain_images("omaha")
        assert [r["title"] for r in results] == ["File:B.jpg", "File:A.jpg"]

    def test_rejects_small_non_image_and_thumbless_files(self, mocker):
        _mock_commons(mocker, ["File:s", "File:t", "File:n", "File:ok"], [
            _page("File:s", width=400), _page("File:t", mime="image/tiff"), _page("File:n", thumb=None), _page("File:ok")])
        assert [r["title"] for r in wr.find_public_domain_images("x")] == ["File:ok"]

    def test_metadata_is_flattened_to_plain_text(self, mocker):
        _mock_commons(mocker, ["File:A.jpg"], [_page("File:A.jpg")])
        r = wr.find_public_domain_images("x")[0]
        assert r["description"] == "A photo" and r["credit"] == "US Navy" and r["license"] == "Public domain"
        assert r["url"] == "https://up/x.jpg" and r["page"] == "https://commons/File:A.jpg"

    def test_limit_applies_after_filtering(self, mocker):
        _mock_commons(mocker, [f"File:{i}" for i in range(5)], [_page(f"File:{i}") for i in range(5)])
        assert len(wr.find_public_domain_images("x", limit=2)) == 2

    def test_never_raises_and_returns_empty_on_failure(self, mocker):
        mocker.patch("httpx.get", side_effect=RuntimeError("down"))
        assert wr.find_public_domain_images("x") == []

    def test_no_search_hits_is_empty(self, mocker):
        _mock_commons(mocker, [], [])
        assert wr.find_public_domain_images("x") == []


class TestStore:
    @pytest.fixture
    def session(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine, tables=[ToonBackground.__table__])
        return sessionmaker(bind=engine)()

    def test_copies_the_photo_to_our_storage_and_records_a_location(self, session, mocker):
        upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/ref.jpg")
        brand = SimpleNamespace(id=uuid.uuid4())
        row = wr.store_scene_reference(session, brand, name="Landing craft approaching Omaha", description="Troops in an LCVP",
                                       country="France", image_bytes=b"jpeg-bytes")
        assert row.image_url == "https://supabase/ref.jpg" and row.brand_id == brand.id
        assert row.description == "Troops in an LCVP" and row.country == "France"
        path, content_type = upload.call_args.args[1], upload.call_args.args[2]
        assert path.startswith(f"world/references/{brand.id}/") and path.endswith(".jpg") and content_type == "image/jpeg"

    def test_png_keeps_its_extension_and_type(self, session, mocker):
        upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/ref.png")
        wr.store_scene_reference(session, SimpleNamespace(id=uuid.uuid4()), name="n", description="d", country=None,
                                 image_bytes=b"png", content_type="image/png")
        assert upload.call_args.args[1].endswith(".png") and upload.call_args.args[2] == "image/png"

    def test_a_long_name_is_truncated_to_the_column_width(self, session, mocker):
        mocker.patch("app.media.storage.upload", return_value="https://supabase/ref.jpg")
        row = wr.store_scene_reference(session, SimpleNamespace(id=uuid.uuid4()), name="x" * 300, description="d",
                                       country=None, image_bytes=b"b")
        assert len(row.name) == 120


class TestFetchImage:
    def test_empty_body_is_an_error(self, mocker):
        mocker.patch("httpx.get", return_value=MagicMock(content=b"", raise_for_status=lambda: None))
        with pytest.raises(wr.ReferenceError):
            wr.fetch_image("https://x/y.jpg")

    def test_sends_a_descriptive_user_agent(self, mocker):
        get = mocker.patch("httpx.get", return_value=MagicMock(content=b"img", raise_for_status=lambda: None))
        assert wr.fetch_image("https://x/y.jpg") == b"img"
        assert "culturix" in get.call_args.kwargs["headers"]["User-Agent"]

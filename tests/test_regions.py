from app.regions import REGION_LABEL_TO_CODES
from app.main import list_regions
import app.pipeline.nodes.persona_mapper as persona_mapper


class TestRegionLabelToCodes:
    def test_expected_labels_present_in_order(self):
        assert list(REGION_LABEL_TO_CODES.keys()) == ["US", "CN", "Global", "EU", "UK", "FR", "CA", "AU"]

    def test_eu_covers_major_european_markets(self):
        assert REGION_LABEL_TO_CODES["EU"] == {"FR", "GB", "ES", "IT", "PT", "DE"}

    def test_uk_aliases_to_gb(self):
        assert REGION_LABEL_TO_CODES["UK"] == {"GB"}


class TestPersonaMapperUsesSharedRegions:
    def test_persona_mapper_imports_the_same_object_not_a_private_copy(self):
        # Regression guard: this is the exact drift that caused a France-only
        # profile to see zero clusters — a picker-facing list and the
        # backend filter's list being two independently-maintained things
        # that silently disagreed. If persona_mapper.py ever goes back to
        # defining its own dict instead of importing app.regions, this
        # `is` check (not just equality) catches it.
        assert persona_mapper._REGION_LABEL_TO_CODES is REGION_LABEL_TO_CODES


class TestListRegionsRoute:
    def test_returns_every_label_with_sorted_codes(self):
        result = list_regions()
        labels = [r["label"] for r in result]
        assert labels == ["US", "CN", "Global", "EU", "UK", "FR", "CA", "AU"]

        eu = next(r for r in result if r["label"] == "EU")
        assert eu["codes"] == sorted(["FR", "GB", "ES", "IT", "PT", "DE"])

        global_entry = next(r for r in result if r["label"] == "Global")
        assert global_entry["codes"] == []

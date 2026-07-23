from app.collectors.region_codes import normalize_region


class TestNormalizeRegion:
    def test_passes_through_already_canonical_codes(self):
        assert normalize_region("US") == "US"
        assert normalize_region("IN") == "IN"
        assert normalize_region("JP") == "JP"

    def test_lowercases_are_upcased(self):
        assert normalize_region("fr") == "FR"

    def test_known_aliases_map_to_canonical_codes(self):
        assert normalize_region("uk") == "GB"
        assert normalize_region("india") == "IN"
        assert normalize_region("japan") == "JP"
        assert normalize_region("us") == "US"
        # France/Canada/Australia are full-name strings (>3 chars), so
        # without an explicit alias they'd hit the long-unrecognized-string
        # fallback below and silently resolve to None — this is exactly the
        # bug that made a "France only" target_regions profile see zero
        # clusters (Twitter, the largest source, sends "france" as a region
        # value through TWITTER_REGIONS, and it needs to resolve to "FR").
        assert normalize_region("france") == "FR"
        assert normalize_region("canada") == "CA"
        assert normalize_region("australia") == "AU"
        assert normalize_region("italy") == "IT"
        assert normalize_region("spain") == "ES"
        assert normalize_region("portugal") == "PT"

    def test_global_maps_to_none(self):
        assert normalize_region("global") is None

    def test_none_and_empty_string_return_none(self):
        assert normalize_region(None) is None
        assert normalize_region("") is None

    def test_long_unrecognized_strings_return_none(self):
        assert normalize_region("some region name") is None

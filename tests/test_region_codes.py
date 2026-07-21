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

    def test_global_maps_to_none(self):
        assert normalize_region("global") is None

    def test_none_and_empty_string_return_none(self):
        assert normalize_region(None) is None
        assert normalize_region("") is None

    def test_long_unrecognized_strings_return_none(self):
        assert normalize_region("some region name") is None

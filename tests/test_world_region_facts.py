import pytest

from app.services.world_region_facts import REGION_FACTS, flag_emoji, region_facts


class TestFlagEmoji:
    def test_builds_the_regional_indicator_pair(self):
        assert flag_emoji("US") == "\U0001F1FA\U0001F1F8"

    def test_lowercase_input_still_works(self):
        assert flag_emoji("us") == flag_emoji("US")

    @pytest.mark.parametrize("bad", [None, "", "USA", "1", "U"])
    def test_invalid_codes_return_none(self, bad):
        assert flag_emoji(bad) is None


class TestRegionFacts:
    def test_a_known_region_returns_facts_plus_flag(self):
        facts = region_facts("US")
        assert facts["capital"] == "Washington, D.C."
        assert facts["currency_code"] == "USD"
        assert facts["flag_emoji"] == flag_emoji("US")

    def test_lowercase_input_matches_the_uppercase_entry(self):
        assert region_facts("us") == region_facts("US")

    def test_an_unknown_region_returns_none_not_an_error(self):
        assert region_facts("ZZ") is None

    def test_none_input_returns_none(self):
        assert region_facts(None) is None

    def test_every_entry_has_the_expected_shape(self):
        required = {"capital", "population_millions", "languages", "currency", "currency_code"}
        for code, facts in REGION_FACTS.items():
            assert len(code) == 2 and code.isupper(), code
            assert required.issubset(facts.keys()), code
            assert isinstance(facts["languages"], list) and facts["languages"], code
            assert isinstance(facts["population_millions"], int) and facts["population_millions"] > 0, code

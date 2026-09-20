"""Period accuracy for World videos: reading years, what belongs in an era, and deciding the era."""
import pytest

from app.services import world_era as we
from app.services.culturetoon_script import ToonScriptGenerationError

ROME = {"label": "Ancient Rome, 753 BC to 27 BC", "start_year": -753, "end_year": -27}
NORMANDY = {"label": "Normandy, June 1944", "start_year": 1944, "end_year": 1944}


class TestParseYears:
    @pytest.mark.parametrize("text,expected", [
        ("In 753 BC, Rome was founded", [-753]),
        ("By 509 BC it was a republic and in 27 BC an empire", [-509, -27]),
        ("The fall in AD 476", [476]),
        ("Constantine died in 337 CE", [337]),
        ("Landings on 6 June 1944 by the Allies", []),          # a bare year needs a word like "in" before it
        ("Landings in 1944", [1944]),
        ("It began in 1789 and ended by 1799", [1789, 1799]),
        ("Around 1200 soldiers and 8,000 ships", []),           # counts are not years
        ("300 BCE to 30 BCE", [-300, -30]),
        ("", []),
    ])
    def test_years(self, text, expected):
        assert we.parse_years(text) == expected

    def test_year_text(self):
        assert we.year_text(-753) == "753 BC" and we.year_text(476) == "476 AD" and we.year_text(1944) == "1944"


class TestBands:
    def test_periods_before_1900_have_a_band_and_later_ones_do_not(self):
        assert we.band_for(ROME)["name"] == "ancient"
        assert we.band_for({"end_year": 1200})["name"] == "medieval"
        assert we.band_for({"end_year": 1650})["name"] == "early_modern"
        assert we.band_for({"end_year": 1850})["name"] == "industrial"
        assert we.band_for(NORMANDY) is None and we.band_for({"end_year": 2020}) is None
        assert we.band_for(None) is None and we.band_for({"end_year": None}) is None

    def test_the_prompt_line_names_the_era_and_what_it_looked_like_in_positive_words(self):
        line = we.era_prompt_line(ROME)
        assert line.startswith("Ancient Rome, 753 BC to 27 BC.") and "terracotta" in line and "ox carts" in line
        assert "Everything on screen belongs to this period" in line
        # Positive wording only: telling a video model what NOT to draw inside the prompt measured worst.
        assert not any(w in line.lower() for w in ("no ", "not ", "without", "never", "car ", "vehicle", "jeep"))

    def test_a_modern_era_gets_only_the_label(self):
        assert we.era_prompt_line(NORMANDY) == "Normandy, June 1944. Everything on screen belongs to this time and place."

    def test_no_era_no_line(self):
        assert we.era_prompt_line(None) == "" and we.era_prompt_line({"label": ""}) == ""

    def test_the_modern_things_go_in_the_negative_prompt(self):
        neg = we.era_negative_terms(ROME)
        for word in ("cars", "jeeps", "asphalt", "khaki", "power lines", "factories"):
            assert word in neg
        assert we.era_negative_terms(NORMANDY) == ""

    def test_each_band_keeps_out_what_it_should_and_lets_in_what_it_had(self):
        assert "chimneys" in we.era_negative_terms(ROME) and "chimneys" not in we.era_negative_terms({"end_year": 1200})
        assert "aircraft" in we.era_negative_terms({"end_year": 1850})


class TestAnachronisms:
    @pytest.mark.parametrize("text,words", [
        ("A jeep drives past the huts", ["jeep"]),
        ("Cars parked by the shore, asphalt roads and chimneys", ["cars", "asphalt", "chimneys"]),
        ("Soldiers in khaki uniforms, a radio antenna", ["khaki", "radio", "antenna"]),
        ("Riflemen fire muskets and cannon", ["muskets", "cannon"]),
        ("An electric street lamp above the road", ["electric", "street lamp"]),
        ("A steamship at the dock, a locomotive on the railway", ["steamship", "locomotive", "railway"]),
    ])
    def test_ancient_rome_rejects_modern_things(self, text, words):
        assert we.find_anachronisms(text, ROME) == words

    @pytest.mark.parametrize("text", [
        "Legionaries in bronze helmets march behind ox carts",
        "Steam rises from the public baths",
        "A trader haggles over a clay amphora as a dog barks",
        "A crowd of citizens gathers at the marble forum",
        "Torches burn along the paved Roman road",           # Roman roads were paved
        "Galleys with oars and square sails leave the harbour",
    ])
    def test_ancient_rome_accepts_what_it_had(self, text):
        assert we.find_anachronisms(text, ROME) == []

    def test_a_medieval_scene_may_have_cannon_but_a_roman_one_may_not(self):
        assert we.find_anachronisms("A cannon fires from the wall", {"end_year": 1400}) == []
        assert we.find_anachronisms("A cannon fires from the wall", ROME) == ["cannon"]

    def test_a_modern_era_is_never_flagged(self):
        assert we.find_anachronisms("A jeep and a tank on the road, radio antenna", NORMANDY) == []
        assert we.find_anachronisms("A jeep", None) == []

    def test_words_are_matched_whole(self):
        assert we.find_anachronisms("A scarce carpet and a busy bustle near the buster", ROME) == []

    def test_check_names_the_shot_and_the_period(self):
        shots = [{"shot_number": 1, "subject_visual": "Villagers by the huts"},
                 {"shot_number": 2, "subject_visual": "A jeep and a truck cross the field", "location": "camp"}]
        problems = we.check_world_anachronisms(shots, ROME)
        assert len(problems) == 1 and problems[0].startswith("Shot 2:") and "'jeep'" in problems[0]
        assert "Ancient Rome, 753 BC to 27 BC" in problems[0]

    def test_check_reads_the_location_and_action_too(self):
        assert we.check_world_anachronisms([{"shot_number": 1, "subject_visual": "ok", "location": "a garage with cars"}], ROME)
        assert we.check_world_anachronisms([{"shot_number": 1, "subject_visual": "ok", "action": "drives a truck"}], ROME)
        assert we.check_world_anachronisms([{"shot_number": 1, "subject_visual": "ok", "location": "a market square"}], ROME) == []

    def test_no_check_for_a_modern_era(self):
        assert we.check_world_anachronisms([{"shot_number": 1, "subject_visual": "a jeep"}], NORMANDY) == []


class TestEraFromText:
    def test_the_curators_words_become_the_label_and_the_years_are_read_from_them(self):
        era = we.era_from_text("Roman Republic, 307 BC to 27 BC")
        assert era == {"label": "Roman Republic, 307 BC to 27 BC", "start_year": -307, "end_year": -27, "source": "curator"}

    def test_a_single_year_is_the_whole_range(self):
        era = we.era_from_text("Rome, 307 BC")
        assert era["start_year"] == era["end_year"] == -307

    @pytest.mark.parametrize("text", ["", "   ", "Roman stuff", "a long time ago"])
    def test_no_year_is_refused_with_an_example(self, text):
        with pytest.raises(we.EraError, match="at least one year"):
            we.era_from_text(text)


class TestCuratorPeriods:
    @pytest.mark.parametrize("text,start,end", [
        ("Normandy, June 1944", 1944, 1944),                 # a lone year is fine when a person typed the period
        ("Rome, 753 BC to 27 BC", -753, -27),
        ("French Revolution 1789-1799", 1789, 1799),
        ("Present day", 2020, 2020),
        ("Modern Istanbul", 2020, 2020),
    ])
    def test_periods_people_type(self, text, start, end):
        era = we.era_from_text(text)
        assert (era["start_year"], era["end_year"]) == (start, end) and era["label"] == text

    def test_present_day_is_a_modern_period_so_the_guard_is_off(self):
        assert we.band_for(we.era_from_text("Present day")) is None

    def test_a_count_in_narration_is_still_not_a_year(self):
        assert we.parse_years("Around 1200 soldiers landed") == []
        assert we.parse_years("Around 1200 soldiers landed", allow_bare=True) == [1200]   # only for typed periods


class TestWidenToNarration:
    def test_a_year_outside_the_era_widens_it(self):
        era = we.widen_to_narration({"label": "x", "start_year": -753, "end_year": -509},
                                    [{"dialogue": "In 27 BC the empire began."}, {"dialogue": "No year here."}])
        assert (era["start_year"], era["end_year"]) == (-753, -27)

    def test_no_years_no_change_and_none_stays_none(self):
        assert we.widen_to_narration(ROME, [{"dialogue": "Rome grew."}]) == ROME
        assert we.widen_to_narration(None, [{"dialogue": "In 27 BC"}]) is None


class TestDetermine:
    def _llm(self, mocker, payload=None, error=None):
        return mocker.patch("app.services.culturetoon_script._call_llm_json", return_value=payload, side_effect=error)

    def test_a_sensible_answer_is_used(self, mocker):
        self._llm(mocker, {"label": "Ancient Rome, 753 BC to 27 BC", "start_year": -753, "end_year": -27})
        era = we.determine_world_era("Rise of the Roman Empire", "Rome, founded in 753 BC ... 27 BC")
        assert era == {"label": "Ancient Rome, 753 BC to 27 BC", "start_year": -753, "end_year": -27, "source": "ai"}

    def test_an_answer_that_contradicts_the_years_the_source_names_is_overridden(self, mocker):
        # The model guessed the Bronze Age for a story about 1944.
        self._llm(mocker, {"label": "Normandy, ancient", "start_year": -1200, "end_year": -1100})
        era = we.determine_world_era("Operation Neptune", "The landings began in 1944 on the coast of Normandy.")
        assert (era["start_year"], era["end_year"]) == (1944, 1944) and "1944" in era["label"]

    def test_a_present_day_subject_gets_a_modern_era_which_turns_the_guard_off(self, mocker):
        self._llm(mocker, {"label": "Present day", "start_year": 2020, "end_year": 2020})
        era = we.determine_world_era("Strait of Hormuz", "A strait between Oman and Iran.")
        assert we.band_for(era) is None

    @pytest.mark.parametrize("payload", [{}, {"label": "x"}, {"label": "", "start_year": 1, "end_year": 2},
                                         {"label": "x", "start_year": "no", "end_year": 5},
                                         {"label": "x", "start_year": -99999, "end_year": 5}])
    def test_junk_is_none(self, mocker, payload):
        self._llm(mocker, payload)
        assert we.determine_world_era("t", "facts") is None

    def test_a_failed_call_is_none_not_an_error(self, mocker):
        self._llm(mocker, error=ToonScriptGenerationError("down"))
        assert we.determine_world_era("t", "facts") is None

    def test_reversed_years_are_put_in_order(self, mocker):
        self._llm(mocker, {"label": "Rome", "start_year": -27, "end_year": -753})
        era = we.determine_world_era("Rome", "no years here")
        assert (era["start_year"], era["end_year"]) == (-753, -27)

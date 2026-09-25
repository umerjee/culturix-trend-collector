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

    def test_a_label_with_no_year_gets_one_appended_so_it_stays_submittable(self, mocker):
        # Confirmed live: a UNESCO subject spanning centuries ("Byzantine to Ottoman") got a
        # correctly-computed start_year/end_year but a label with no digits at all — which a
        # curator then can't submit as-is, since era_from_text() only has the label text to
        # re-parse (it never sees start_year/end_year) and rejects anything with no year.
        self._llm(mocker, {"label": "Istanbul, Byzantine to Ottoman", "start_year": 330, "end_year": 1922})
        era = we.determine_world_era("Threats to Istanbul's Masterpieces", "Byzantine and Ottoman heritage.")
        assert we.parse_years(era["label"], allow_bare=True)
        # The fix must not just be submittable — it must re-parse to the SAME years already computed.
        resubmitted = we.era_from_text(era["label"])
        assert (resubmitted["start_year"], resubmitted["end_year"]) == (330, 1922)

    def test_a_label_that_already_has_a_year_is_left_exactly_as_the_model_wrote_it(self, mocker):
        self._llm(mocker, {"label": "Ancient Rome, 753 BC to 27 BC", "start_year": -753, "end_year": -27})
        era = we.determine_world_era("Rise of the Roman Empire", "Rome, founded in 753 BC ... 27 BC")
        assert era["label"] == "Ancient Rome, 753 BC to 27 BC"


KINGDOM = {"from_year": -753, "to_year": -509, "label": "Roman Kingdom",
           "look": "Simple huts of wattle and daub with thatched roofs. Narrow unpaved dirt paths.",
           "avoid": ["marble", "columns", "tile", "aqueducts"]}
REPUBLIC = {"from_year": -508, "to_year": -27, "label": "Roman Republic",
            "look": "Stone and brick buildings with tiled roofs and paved streets.", "avoid": ["concrete", "domes"]}
ROME_PHASES = {"label": "Ancient Rome, 753 BC to 27 BC", "start_year": -753, "end_year": -27, "phases": [KINGDOM, REPUBLIC]}


def _shot(n, dialogue="", visual="Villagers run past huts", **kw):
    return {"shot_number": n, "dialogue": dialogue, "subject_visual": visual, **kw}


class TestPhaseLookup:
    @pytest.mark.parametrize("year,label", [(-753, "Roman Kingdom"), (-509, "Roman Kingdom"), (-508, "Roman Republic"),
                                            (-27, "Roman Republic"), (-900, "Roman Kingdom"), (100, "Roman Republic")])
    def test_the_phase_containing_the_year_or_the_nearest_one(self, year, label):
        assert we.phase_for_year(ROME_PHASES, year)["label"] == label

    def test_no_phases_or_no_year(self):
        assert we.phase_for_year(ROME, -700) is None and we.phase_for_year(None, -700) is None
        assert we.phase_for_year(ROME_PHASES, None)["label"] == "Roman Kingdom"      # unknown year: the start of the story


class TestShotYears:
    def test_the_narrations_own_year_wins_over_the_writers(self):
        shots = [_shot(1, "In 753 BC Rome began.", year=-27)]
        assert we.shot_years(shots, ROME_PHASES) == [-753]

    def test_the_writers_year_is_used_when_the_narration_names_none(self):
        assert we.shot_years([_shot(1, "Rome grew.", year=-509)], ROME_PHASES) == [-509]

    @pytest.mark.parametrize("bad", [None, "1944", True, 99999, -99999])
    def test_a_junk_writer_year_is_ignored(self, bad):
        assert we.shot_years([_shot(1, "Rome grew.", year=bad)], ROME_PHASES) == [-753]     # falls back to the era's start

    def test_a_shot_with_no_year_carries_the_previous_ones(self):
        shots = [_shot(1, "By 509 BC it was a republic."), _shot(2, "It expanded."), _shot(3, "Later still.")]
        assert we.shot_years(shots, ROME_PHASES) == [-509, -509, -509]

    def test_assigning_periods_sets_the_year_and_the_phase_index(self):
        shots = [_shot(1, "In 753 BC..."), _shot(2, "In 27 BC...")]
        out = we.assign_shot_periods(shots, ROME_PHASES)
        assert [(s["period_year"], s["period_phase"]) for s in out] == [(-753, 0), (-27, 1)]
        assert "period_year" not in shots[0]                                               # inputs are not mutated

    def test_an_era_without_phases_leaves_shots_unchanged(self):
        assert we.assign_shot_periods([_shot(1, "In 753 BC")], ROME) == [_shot(1, "In 753 BC")]


class TestPhasePromptAndChecks:
    def test_the_prompt_line_describes_the_shots_own_place_and_year(self):
        line = we.era_prompt_line(ROME_PHASES, KINGDOM, -753)
        assert line == ("Ancient Rome, 753 BC to 27 BC. Roman Kingdom (753 BC): Simple huts of wattle and daub with thatched "
                        "roofs. Narrow unpaved dirt paths. Everything on screen belongs to this period.")
        assert "marble" not in line and "terracotta" not in line          # not the generic ancient-world description

    def test_without_a_phase_it_falls_back_to_the_generic_band(self):
        assert "terracotta" in we.era_prompt_line(ROME_PHASES, None, None)

    def test_the_negative_terms_add_what_did_not_exist_in_that_phase(self):
        neg = we.era_negative_terms(ROME_PHASES, KINGDOM)
        assert neg.startswith("cars, trucks") and neg.endswith("marble, columns, tile, aqueducts")
        assert we.era_negative_terms(ROME_PHASES, REPUBLIC).endswith("concrete, domes")
        assert we.era_negative_terms(NORMANDY, KINGDOM) == ""

    def test_a_phase_term_is_matched_as_a_whole_word_and_plural(self):
        assert we.find_anachronisms("Marble columns rise", ROME_PHASES, KINGDOM) == ["marble", "columns"]
        assert we.find_anachronisms("A column of soldiers marches", ROME_PHASES, KINGDOM) == []       # 'column' is not 'columns'
        assert we.find_anachronisms("Tiles glint on a roof", ROME_PHASES, KINGDOM) == ["tile"]
        assert we.find_anachronisms("The marbled sky", ROME_PHASES, KINGDOM) == []

    def test_each_shot_is_checked_against_its_own_phase(self):
        shots = [_shot(1, "In 753 BC Rome began.", visual="Marble columns rise over huts"),
                 _shot(2, "In 27 BC an empire.", visual="Marble columns rise over a forum")]
        problems = we.check_world_anachronisms(shots, ROME_PHASES)
        assert len(problems) == 1 and problems[0].startswith("Shot 1:") and "Roman Kingdom (753 BC)" in problems[0]

    def test_a_later_phase_may_have_what_an_earlier_one_did_not(self):
        assert we.check_world_anachronisms([_shot(1, "In 27 BC an empire.", visual="A tiled roof over a stone forum")], ROME_PHASES) == []


class TestPeriodPhasesFromTheModel:
    def _llm(self, mocker, payload=None, error=None):
        return mocker.patch("app.services.culturetoon_script._call_llm_json", return_value=payload, side_effect=error)

    def test_phases_are_cleaned_ordered_and_capped(self, mocker):
        raw = [{"from_year": -508, "to_year": -27, "label": "Republic", "look": "Brick.", "avoid": ["Domes", "domes", "x", " concrete "]},
               {"from_year": -753, "to_year": -509, "label": "Kingdom", "look": "Huts.", "avoid": ["marble"] * 3},
               {"from_year": "no", "to_year": 1, "label": "bad", "look": "x"}, {"label": "no years", "look": "x"}, "junk",
               {"from_year": 1, "to_year": 2, "label": "", "look": "no label"}] + \
              [{"from_year": i, "to_year": i + 1, "label": f"p{i}", "look": "l"} for i in range(10, 20)]
        self._llm(mocker, {"phases": raw})
        phases = we.period_phases("Ancient Rome", -753, -27, "Rome", "facts")
        assert [p["label"] for p in phases][:2] == ["Kingdom", "Republic"] and len(phases) == we.MAX_PHASES
        assert phases[0]["avoid"] == ["marble"] and phases[1]["avoid"] == ["domes", "concrete"]     # lowercased, de-duplicated, short ones dropped

    def test_the_prompt_asks_for_certainty_and_gives_the_period(self, mocker):
        call = self._llm(mocker, {"phases": []})
        we.period_phases("Ancient Rome, 753 BC to 27 BC", -753, -27, "Rise of Rome", "Rome was founded")
        prompt = call.call_args.args[0]
        assert "753 BC to 27 BC" in prompt and "CERTAIN" in prompt and "Rome was founded" in prompt

    def test_a_failed_call_is_no_phases(self, mocker):
        self._llm(mocker, error=ToonScriptGenerationError("down"))
        assert we.period_phases("x", -753, -27, "t", "f") == []

    def test_attach_adds_phases_once_and_only_for_an_era_that_needs_them(self, mocker):
        call = mocker.patch("app.services.world_era.period_phases", return_value=[KINGDOM])
        attached = we.attach_phases(ROME, "Rome", "facts")
        assert attached["phases"] == [KINGDOM] and attached["label"] == ROME["label"]
        assert we.attach_phases(attached, "Rome", "facts") is attached           # already has them
        assert we.attach_phases(NORMANDY, "D-Day", "facts") is NORMANDY          # a modern era needs none
        assert we.attach_phases(None, "x", "y") is None
        assert call.call_count == 1

    def test_a_failed_description_leaves_the_era_as_it_was(self, mocker):
        mocker.patch("app.services.world_era.period_phases", return_value=[])
        assert we.attach_phases(ROME, "Rome", "facts") is ROME

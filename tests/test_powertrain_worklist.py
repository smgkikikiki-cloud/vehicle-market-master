"""The judgement in the powertrain work list: what counts as evidence."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from powertrain_worklist import (  # noqa: E402
    CONFIRMS, CONFLICT, NO_SIGNAL, classify, labels_say,
)


class TestLabelsSay:
    def test_a_powertrain_word_is_read_from_the_label(self):
        assert labels_say(["HONDA JAZZ HYBRID'12"]) == {"HEV"}
        assert labels_say(["BYD BYD SEAL 5 DM-i DYNAMIC"]) == {"PHEV"}
        assert labels_say(["MITSUBISHI XFORCE HEV"]) == {"HEV"}
        assert labels_say(["MERCEDES BENZ S 500L MILD HYBRID"]) == {"MHEV"}

    def test_turbo_is_not_a_powertrain(self):
        """A Taycan Turbo is battery-electric and a Cayenne Turbo is not.

        The first run of this list called the Taycan a combustion car on the
        strength of its trim name.
        """
        assert labels_say(["PORSCHE TAYCAN TURBO CROSS TURISMO"]) == set()

    def test_an_injection_system_is_not_a_powertrain(self):
        """TFSI and TSI were markers for combustion until they were not.

        Audi puts TFSI on mild hybrids, so the badge said nothing about
        electrification and the list spent two of its ten findings arguing
        with a catalog entry that was right.
        """
        assert labels_say(["AUDI A5 CP 40 TFSI S line"]) == set()
        assert labels_say(["AUDI TT Coupe 45 TFSI q S line"]) == set()

    def test_mild_hybrid_is_claimed_before_plain_hybrid(self):
        """A mild hybrid is a combustion car; reading it as HEV moves it into
        the electrified column and it does not belong there."""
        assert labels_say(["BMW 430D CONVERTIBLE Mild-hybrid"]) == {"MHEV"}
        assert labels_say(["TOYOTA SIENTA HYBRID Z"]) == {"HEV"}

    def test_a_bare_nameplate_says_nothing(self):
        assert labels_say(["TOYOTA COROLLA CROSS", "TOYOTA Corolla Cross"]) \
            == set()

    def test_trim_spellings_and_battery_sizes_are_not_evidence(self):
        """Counting distinct labels was the first idea and it was worthless.

        The D-Max has five spellings, the Ranger's extra labels are the Raptor
        and the Dolphin's are range figures. None of it is about powertrain.
        """
        assert labels_say(["ISUZU D-MAX", "ISUZU D-MAX New Style",
                           "ISUZU CAB4 SL 2.5"]) == set()
        assert labels_say(["FORD RANGER", "FORD RANGER RAPTOR"]) == set()


class TestClassify:
    def test_silence_is_its_own_answer(self):
        assert classify("ICE", set()) == NO_SIGNAL

    def test_a_word_that_backs_the_claim_is_low_risk(self):
        assert classify("HEV", {"HEV"}) == CONFIRMS

    def test_a_word_against_the_claim_is_a_conflict(self):
        assert classify("ICE", {"HEV"}) == CONFLICT
        assert classify("BEV", {"PHEV"}) == CONFLICT

    def test_two_words_are_a_conflict_even_when_one_matches(self):
        # A nameplate sold both ways belongs at MIXED, not at either word.
        assert classify("PHEV", {"HEV", "PHEV"}) == CONFLICT

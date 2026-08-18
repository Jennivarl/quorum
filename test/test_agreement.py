"""
Unit tests for the agreement rules (contracts/agreement.py).

The cases that matter most are the ones where sources differ in wording but
not in substance, and the mirror cases where they look similar and mean
different things. Getting either wrong turns the oracle into theatre: one
direction manufactures disagreement out of rounding, the other reports
consensus that does not exist.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contracts.agreement import (
    KIND_ABSTAIN,
    KIND_BOOLEAN,
    KIND_DATE,
    KIND_NUMERIC,
    KIND_PERCENT,
    KIND_TEXT,
    assess,
    classify,
)


def ex(source, raw):
    return classify(source, raw)


# --- classification -------------------------------------------------------

def test_percentages_are_recognised_in_several_forms():
    for raw in ["40%", "40 percent", "40 per cent", "40pct"]:
        got = classify("s", raw)
        assert got.kind == KIND_PERCENT
        assert got.value == 40.0


def test_ratios_are_read_as_percentages():
    assert classify("s", "two in five").value == 40.0
    assert classify("s", "1 in 4").value == 25.0


def test_scaled_numbers_are_expanded():
    assert classify("s", "3.2 million").value == 3_200_000
    assert classify("s", "40k").value == 40_000
    assert classify("s", "1,250").value == 1250


def test_iso_and_named_dates_both_parse():
    assert classify("s", "2026-03-14").kind == KIND_DATE
    assert classify("s", "14 March 2026").value == classify("s", "2026-03-14").value
    assert classify("s", "March 14, 2026").value == classify("s", "2026-03-14").value


def test_ambiguous_numeric_dates_are_not_guessed():
    # 03/04/2026 is March in one country and April in another. Guessing
    # would silently invent agreement or disagreement.
    assert classify("s", "03/04/2026").kind != KIND_DATE


def test_yes_and_no_are_recognised():
    assert classify("s", "Yes").kind == KIND_BOOLEAN
    assert classify("s", "no, the filing was withdrawn").value == 0.0


def test_silence_is_abstention_not_an_answer():
    for raw in ["", "unknown", "not stated", "N/A", "not mentioned"]:
        assert classify("s", raw).kind == KIND_ABSTAIN


def test_prose_falls_through_to_text():
    assert classify("s", "the market reacted badly").kind == KIND_TEXT


# --- agreement ------------------------------------------------------------

def test_rounded_percentages_agree():
    """38.7% and "about 40 percent" are the same claim reported differently."""
    result = assess([ex("a", "38.7%"), ex("b", "about 40 percent"), ex("c", "39%")])
    assert result.verdict == "corroborated"
    assert result.dissenting == []


def test_genuinely_different_percentages_disagree():
    result = assess([ex("a", "12%"), ex("b", "64%")])
    assert result.verdict == "contested"


def test_small_percentages_are_not_split_by_relative_tolerance():
    # 0.1 and 0.2 differ by 100% relatively but are the same claim in
    # substance, which is why an absolute point tolerance exists.
    result = assess([ex("a", "0.1%"), ex("b", "0.2%")])
    assert result.verdict == "corroborated"


def test_majority_is_reported_with_the_dissenter_named():
    """The dissent record is the whole point of corroborating."""
    result = assess([ex("a", "40%"), ex("b", "41%"), ex("c", "12%")])
    assert result.verdict == "majority"
    assert result.agreeing == ["a", "b"]
    assert result.dissenting == ["c"]
    assert result.agreement_ratio_percent == 66


def test_an_even_split_is_contested_not_a_majority():
    result = assess([ex("a", "40%"), ex("b", "41%"), ex("c", "12%"), ex("d", "11%")])
    assert result.verdict == "contested"


def test_verdict_does_not_depend_on_source_order():
    """
    Scoring every candidate rather than trusting the first reply. If the
    verdict moved when the sources were listed differently, the oracle
    would be reporting arrival order rather than corroboration.
    """
    forward = assess([ex("a", "12%"), ex("b", "40%"), ex("c", "41%")])
    reverse = assess([ex("c", "41%"), ex("b", "40%"), ex("a", "12%")])
    assert forward.verdict == reverse.verdict == "majority"
    assert set(forward.agreeing) == set(reverse.agreeing) == {"b", "c"}


def test_abstentions_do_not_count_against_agreement():
    # A source that is silent on a claim is not evidence against it.
    result = assess([ex("a", "40%"), ex("b", "41%"), ex("c", "not stated")])
    assert result.verdict == "corroborated"
    assert result.abstaining == ["c"]
    assert result.agreement_ratio_percent == 100


def test_all_sources_silent_is_no_data_not_agreement():
    """
    Zero answers must never read as unanimous. This is the failure that
    would let an empty result look like a confirmed fact.
    """
    result = assess([ex("a", "unknown"), ex("b", "")])
    assert result.verdict == "no_data"
    assert result.agreement_ratio_percent == 0


def test_conflicting_booleans_are_contested():
    result = assess([ex("a", "yes"), ex("b", "no")])
    assert result.verdict == "contested"


def test_dates_require_exact_agreement():
    result = assess([ex("a", "2026-03-14"), ex("b", "2026-03-15")])
    assert result.verdict == "contested"


def test_prose_is_handed_to_the_model():
    result = assess([ex("a", "rose sharply"), ex("b", "fell slightly")])
    assert result.needs_model is True
    assert result.verdict == "needs_judgment"


def test_mixed_kinds_are_handed_to_the_model():
    # One source answering "yes" and another "40%" cannot be compared by
    # arithmetic; whether they agree depends on the question.
    result = assess([ex("a", "yes"), ex("b", "40%")])
    assert result.needs_model is True


def test_single_source_is_corroborated_by_nothing():
    """
    One source agreeing with itself is not corroboration. The ratio is
    100% because everything that answered agreed, so the verdict alone is
    never enough; a caller has to read the source count too.
    """
    result = assess([ex("a", "40%")])
    assert result.verdict == "corroborated"
    assert len(result.agreeing) == 1


# Ranges were found broken by running real archived sources through the
# engine. Wikipedia says Lagos has "between 17 and 21 million" residents,
# and that parsed as the number 17, because the scale word was not adjacent
# to the first figure. It disagreed with every other source by a factor of
# a million, and did so for entirely the wrong reason.
def test_a_stated_range_uses_its_midpoint():
    got = classify("s", "between 17 and 21 million")
    assert got.kind == KIND_NUMERIC
    assert got.value == 19_000_000


def test_range_scale_word_applies_to_both_ends():
    assert classify("s", "13 to 15 million").value == 14_000_000
    assert classify("s", "1.5 to 2.5 billion").value == 2_000_000_000


def test_range_without_a_scale_word_still_works():
    assert classify("s", "400 to 600").value == 500


def test_a_range_agrees_with_a_figure_inside_it():
    # Wikipedia's range and a point estimate near its middle are the same
    # claim, and must not be recorded as a dissent.
    result = assess([ex("a", "between 17 and 21 million"), ex("b", "18,600,000")])
    assert result.verdict == "corroborated"


def test_a_range_disagrees_with_a_figure_well_outside_it():
    result = assess([ex("a", "between 17 and 21 million"), ex("b", "13,491,800")])
    assert result.verdict == "contested"

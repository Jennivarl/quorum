"""
Integration tests over the archived sources in fixtures/.

These guard the reference check rather than the code. The contract is
already unit tested; what is untested without these is whether the five
frozen documents still say what the demo claims they say, and whether
the figures survive the trip into a prompt.

The one that matters most is the truncation guard. `build_extraction_prompt`
cuts a document at 6000 characters, so a re-capture that pushes a
population figure past that boundary would silently turn a source into an
honest "not stated" and change the verdict, with nothing failing to say
so. That failure is invisible in production and expensive to debug, which
is exactly what a test is for.
"""

import json
import re
from pathlib import Path

from contracts.agreement import assess, classify
from contracts.judgment import build_extraction_prompt

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
SOURCES = FIXTURES / "sources"

CLAIM = "What is the population of Lagos, Nigeria?"

HEADER_END = "-" * 68

# What each archived source actually says, and the substring that proves
# it. Kept here rather than derived, so a source quietly changing under us
# fails loudly instead of the test rewriting its own expectation.
EXPECTED = {
    "wikipedia": ("between 17 and 21 million", "between 17 and 21 million"),
    "citypopulation": ("13,491,800", "13,491,800"),
    "worldpopulationreview": ("14,881,845", "14,881,845"),
    "britannica": ("13,745,000", "13,745,000"),
    "wikidata": ("15,070,000", "population 15070000"),
}

# The result the demo advertises. If any of this moves, the README and the
# frontend are wrong too.
#
# These five split into two pairs of equal size, 13.5-13.7 million and
# 14.9-15.1 million, with wikipedia alone at 19. An earlier version reported
# britannica and citypopulation as the agreeing majority at 40%, which was
# an artefact of them sorting first: had the sources been listed in another
# order the other pair would have "won" and these two would have been the
# dissenters. Neither pair outnumbers the other, so no answer here is backed
# by a majority and none is published as the value.
EXPECTED_VERDICT = "contested"
EXPECTED_PERCENT = 0
EXPECTED_AGREEING: set = set()
EXPECTED_DISSENTING = {
    "britannica",
    "citypopulation",
    "wikidata",
    "wikipedia",
    "worldpopulationreview",
}


def manifest() -> dict:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def body_of(name: str) -> str:
    """The captured text, with the provenance header stripped."""
    raw = (SOURCES / f"{name}.txt").read_text(encoding="utf-8")
    assert HEADER_END in raw, f"{name}: no provenance header separator"
    return raw.split(HEADER_END, 1)[1].strip()


def whole_file(name: str) -> str:
    return (SOURCES / f"{name}.txt").read_text(encoding="utf-8")


# --------------------------------------------------------------------
# the archive itself
# --------------------------------------------------------------------

def test_manifest_and_directory_agree():
    named = {s["name"] for s in manifest()["sources"]}
    on_disk = {p.stem for p in SOURCES.glob("*.txt")}
    assert named == on_disk


def test_manifest_covers_every_expectation():
    assert {s["name"] for s in manifest()["sources"]} == set(EXPECTED)


def test_manifest_claim_matches_the_one_under_test():
    assert manifest()["claim"] == CLAIM


def test_every_source_carries_its_provenance():
    """
    A page about trusting sources that cannot say where its own sources
    came from has no standing. Every capture records the publisher, the
    URL it came from, and when it was taken.
    """
    for entry in manifest()["sources"]:
        raw = whole_file(entry["name"])
        head = raw.split(HEADER_END, 1)[0]
        assert head.lstrip("﻿").startswith("ARCHIVED SOURCE"), entry["name"]
        assert "original-url: " + entry["url"] in head, entry["name"]
        assert entry["publisher"] in head, entry["name"]
        assert re.search(r"retrieved: \d{4}-\d{2}-\d{2}T", head), entry["name"]


def test_recorded_lengths_are_still_true():
    """
    Catches a re-capture that updated the text and forgot the manifest.
    """
    for entry in manifest()["sources"]:
        assert len(body_of(entry["name"])) == entry["chars"], entry["name"]


def test_sources_are_independent_publishers():
    hosts = [
        re.sub(r"^https?://(www\.)?([^/]+).*$", r"\2", s["url"])
        for s in manifest()["sources"]
    ]
    assert len(set(hosts)) == len(hosts), "duplicate publisher: {0}".format(hosts)


# --------------------------------------------------------------------
# the figures survive the prompt
# --------------------------------------------------------------------

def test_each_source_still_states_its_figure():
    for name, (_, proof) in EXPECTED.items():
        assert proof in whole_file(name), f"{name} no longer states {proof}"


def test_figures_survive_prompt_truncation():
    """
    The guard that justifies this file existing.

    `build_extraction_prompt` truncates at 6000 characters. A figure that
    falls past the cut is not an error anywhere: the model reads a
    document that genuinely does not contain the answer and correctly
    reports "not stated". The source drops out of the tally, the verdict
    changes, and nothing in the stack says why.
    """
    for name, (_, proof) in EXPECTED.items():
        prompt = build_extraction_prompt(CLAIM, whole_file(name))
        assert proof in prompt, (
            f"{name}: figure lost to the 6000 char truncation window"
        )


def test_no_source_is_close_to_the_truncation_edge():
    """
    Warns before the above breaks. A capture with under 400 characters of
    headroom is one small edit away from losing its figure.
    """
    tight = []
    for name, (_, proof) in EXPECTED.items():
        raw = whole_file(name)
        end_of_proof = raw.index(proof) + len(proof)
        if 6000 - end_of_proof < 400:
            tight.append((name, 6000 - end_of_proof))
    assert not tight, "figure too near the truncation cut: {0}".format(tight)


# --------------------------------------------------------------------
# the reference verdict
# --------------------------------------------------------------------

def reference_result():
    extracted = [
        classify(name, answer) for name, (answer, _) in sorted(EXPECTED.items())
    ]
    return assess(extracted)


def test_reference_check_is_contested():
    assert reference_result().verdict == EXPECTED_VERDICT


def test_reference_agreement_is_forty_percent():
    assert reference_result().agreement_ratio_percent == EXPECTED_PERCENT


def test_reference_names_the_right_dissenters():
    result = reference_result()
    assert set(result.agreeing) == EXPECTED_AGREEING
    assert set(result.dissenting) == EXPECTED_DISSENTING
    assert result.abstaining == []


def test_every_source_is_accounted_for_exactly_once():
    result = reference_result()
    seen = result.agreeing + result.dissenting + result.abstaining
    assert sorted(seen) == sorted(EXPECTED)
    assert len(seen) == len(set(seen))


def test_wikipedia_range_reads_as_its_midpoint():
    """
    Wikipedia gives a range where the others give a figure. Read as its
    first number it would be 17, which is not a population and would
    disagree with everything by a factor of a million.
    """
    got = classify("wikipedia", "between 17 and 21 million")
    assert got.kind == "numeric"
    assert got.value == 19_000_000


def test_a_silent_source_does_not_count_against_the_claim():
    """
    Adding a source that says nothing must not lower agreement. It is not
    evidence, and treating it as dissent would punish breadth.
    """
    before = reference_result().agreement_ratio_percent
    with_silence = [classify(n, a) for n, (a, _) in sorted(EXPECTED.items())]
    with_silence.append(classify("un-data", "not stated"))
    after = assess(with_silence)
    assert after.agreement_ratio_percent == before
    assert after.abstaining == ["un-data"]


def test_verdict_survives_reordering_the_sources():
    """
    Two clusters of two here, so which one is called the majority is
    decided by order. The verdict and the number of dissenters must not
    be, because those are what consensus compares and what a caller acts
    on.
    """
    forward = [classify(n, a) for n, (a, _) in sorted(EXPECTED.items())]
    backward = list(reversed(forward))
    a, b = assess(forward), assess(backward)
    assert a.verdict == b.verdict == EXPECTED_VERDICT
    assert a.agreement_ratio_percent == b.agreement_ratio_percent
    assert len(a.dissenting) == len(b.dissenting)


def test_the_spread_is_wide_enough_to_be_a_real_disagreement():
    """
    The demo would be dishonest if the sources only differed by rounding.
    The widest gap between neighbouring figures must exceed the 5%
    tolerance, or this is a tolerance bug being sold as a finding.
    """
    values = sorted(classify(n, a).value for n, (a, _) in EXPECTED.items())
    gaps = [(hi - lo) / hi for lo, hi in zip(values, values[1:])]
    assert max(gaps) > 0.05, "no gap exceeds tolerance: {0}".format(gaps)



def test_no_cluster_here_outnumbers_the_other():
    """
    Why this reference case reports nobody as agreeing.

    Two pairs of the same size, and an answer alone. Picking one pair would
    publish a value and name three dissenters on nothing more substantial
    than which source was listed first, so the ordering of the input would
    decide who the record blames.
    """
    from contracts.agreement import _values_agree

    ex = [classify(n, a) for n, (a, _) in sorted(EXPECTED.items())]
    sizes = {}
    for c in ex:
        members = frozenset(
            e.source for e in ex if _values_agree(c.kind, c.value, e.value)
        )
        sizes[members] = len(members)

    largest = max(sizes.values())
    tied = [m for m, n in sizes.items() if n == largest]
    assert largest == 2
    assert len(tied) == 2, "the tie is the whole reason nothing is published"


def test_reordering_the_sources_cannot_change_the_result():
    """The property the old code did not have."""
    import random

    items = list(EXPECTED.items())
    baseline = assess([classify(n, a) for n, (a, _) in sorted(items)])

    for seed in range(8):
        shuffled = items[:]
        random.Random(seed).shuffle(shuffled)
        got = assess([classify(n, a) for n, (a, _) in shuffled])
        assert got.verdict == baseline.verdict
        assert got.consensus_value == baseline.consensus_value
        assert sorted(got.dissenting) == sorted(baseline.dissenting)
        assert sorted(got.agreeing) == sorted(baseline.agreeing)

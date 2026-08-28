"""
Tests for the parts consensus newly covers.

A steward review found the real hole in the earlier design: validators
attested the verdict and the dissent lists, but not the per-source answers
or the quotations. Those are the fields a reader treats as evidence, and
nothing stopped a leader inventing them.

Two rules close it, and both are deterministic, which is what makes them
usable inside a validator:

  a quote is evidence only if it appears in the document
  a stored value is attested only if another node reads the same value

Independence is enforced in the same spirit. Five pages from one publisher
is not corroboration, and the stored record could not previously tell the
difference.
"""

from contracts.agreement import (
    KIND_ABSTAIN,
    answer_grounded_in_quote,
    answers_attest,
    classify,
    host_of,
    normalize_space,
    quote_is_verbatim,
    same_publisher,
)


DOC = """
    Lagos State      5,725,116   9,113,605   13,491,800
    Source: National Population Commission of Nigeria.
    All population figures for Nigeria show high error rates;
    census results are disputed.
"""


# --------------------------------------------------------------------
# quotes
# --------------------------------------------------------------------

def test_a_verbatim_quote_is_accepted():
    assert quote_is_verbatim("Lagos State 5,725,116 9,113,605 13,491,800", DOC)


def test_whitespace_differences_do_not_matter():
    """
    Page rendering collapses runs of space unpredictably, so a quote that
    survived a different amount of it is still the same span.
    """
    assert quote_is_verbatim("census   results\n\n  are disputed", DOC)


def test_a_paraphrase_is_rejected():
    """
    The whole point. A model that reworded the sentence has not quoted it,
    and presenting that as a quotation is what this catches.
    """
    assert not quote_is_verbatim("Lagos State had 13.5 million people", DOC)


def test_a_fabricated_quote_is_rejected():
    assert not quote_is_verbatim(
        "The population is definitively 20,000,000 residents", DOC
    )


def test_case_changes_are_rejected():
    """
    No case folding. A quotation that changed the text is not verbatim, and
    being lenient here would slowly turn the check into a similarity score.
    """
    assert not quote_is_verbatim("CENSUS RESULTS ARE DISPUTED", DOC)


def test_an_empty_quote_is_never_evidence():
    assert not quote_is_verbatim("", DOC)
    assert not quote_is_verbatim("   \n  ", DOC)


def test_normalize_space_preserves_case_and_content():
    assert normalize_space("  A   b\n\tc  ") == "A b c"


# --------------------------------------------------------------------
# answers
# --------------------------------------------------------------------

def test_the_same_number_written_differently_still_attests():
    assert answers_attest("13,491,800", "13491800")


def test_values_inside_tolerance_attest():
    """
    Two models reading the same table can round differently. Within the
    same tolerance used everywhere else, that is the same claim.
    """
    assert answers_attest("13,491,800", "13,500,000")


def test_values_outside_tolerance_do_not_attest():
    assert not answers_attest("13,491,800", "17,000,000")


def test_percent_and_number_are_different_kinds():
    assert not answers_attest("40%", "40")


def test_dates_must_match_exactly():
    assert answers_attest("2026-03-21", "21 March 2026")
    assert not answers_attest("2026-03-21", "2026-03-22")


def test_yes_and_no_do_not_attest_each_other():
    assert answers_attest("yes", "confirmed")
    assert not answers_attest("yes", "no")


def test_prose_is_not_compared_as_text():
    """
    Deliberate. Wording genuinely varies between models, so prose is
    attested by its quote being real and by the reconciliation step, not by
    string comparison. Demanding equality here would fail honest checks.
    """
    assert answers_attest(
        "the figure rose sharply over the period",
        "there was a steep increase across those years",
    )


def test_prose_containing_a_number_word_is_read_as_a_number():
    """
    Documenting a sharp edge rather than pretending it is not there.

    `classify` scans for number words, so "across the ten years" is read as
    the value 10 and stops being prose. Against a genuinely wordy answer it
    then looks like a kind mismatch and fails to attest, which is the safe
    direction to fail in: the check is rejected rather than a mismatched
    value being stored. Worth knowing before debugging a puzzling refusal.
    """
    assert not answers_attest(
        "the figure rose sharply over the period",
        "there was a steep increase across the ten years",
    )


def test_an_answer_and_a_silence_do_not_attest():
    assert not answers_attest("13,491,800", "")
    assert not answers_attest("", "13,491,800")


def test_two_silences_attest():
    assert answers_attest("", "not stated")


# --------------------------------------------------------------------
# source independence
# --------------------------------------------------------------------

def test_host_extraction():
    cases = [
        ("https://www.britannica.com/place/Lagos-Nigeria", "britannica.com"),
        ("http://citypopulation.de/en/nigeria/", "citypopulation.de"),
        ("https://en.wikipedia.org/api/rest_v1/page/summary/Lagos", "en.wikipedia.org"),
        ("https://example.com:8443/x?y=1#z", "example.com"),
        ("https://user@example.org/path", "example.org"),
        ("HTTPS://WWW.Example.COM/Path", "example.com"),
    ]
    for url, expected in cases:
        assert host_of(url) == expected, url


def test_the_reference_sources_are_independent_publishers():
    origins = [
        "https://en.wikipedia.org/api/rest_v1/page/summary/Lagos",
        "https://www.citypopulation.de/en/nigeria/admin/NGA025__lagos/",
        "https://worldpopulationreview.com/cities/nigeria/lagos",
        "https://www.britannica.com/place/Lagos-Nigeria",
        "https://www.wikidata.org/wiki/Special:EntityData/Q8673.json",
    ]
    hosts = [host_of(o) for o in origins]
    assert len(set(hosts)) == len(hosts), hosts


def test_archived_copies_from_one_host_count_as_one_publisher():
    """
    The cost of judging independence on the fetched URL, stated plainly.

    Every frozen fixture is served from raw.githubusercontent.com, so a
    check built entirely out of them is now rejected even though the claims
    were published independently. An earlier version avoided that by
    letting the caller name the publisher separately, which made the whole
    test caller-controlled: two pages from one publisher passed by
    declaring different origins.

    Refusing checks that might be independent is the safe direction to
    fail. Accepting checks that are not independent is the one that makes
    the stored verdict a lie.
    """
    archived = [
        "https://raw.githubusercontent.com/Jennivarl/quorum/abc/fixtures/sources/wikipedia.txt",
        "https://raw.githubusercontent.com/Jennivarl/quorum/abc/fixtures/sources/britannica.txt",
    ]
    assert len({host_of(a) for a in archived}) == 1


def test_a_declared_publisher_cannot_split_one_host_into_two():
    """
    The exact bypass the rejection named, kept as a regression.

    Two pages from one publisher, each declaring a different origin. Under
    the old rule these were two hosts and the check was accepted. The rule
    now reads the URL that was actually fetched, and no value the caller
    supplies participates in the decision.
    """
    urls = [
        "https://example-news.com/story/one",
        "https://example-news.com/story/two",
    ]
    declared = ["https://reuters.com/a", "https://apnews.com/b"]

    assert len({host_of(o) for o in declared}) == 2, "the bypass really did split"
    assert len({host_of(u) for u in urls}) == 1, "the fetched host does not"


# --------------------------------------------------------------------
# layer two: is the figure actually inside the quote
# --------------------------------------------------------------------

from contracts.agreement import answer_grounded_in_quote, numbers_in
from contracts.judgment import build_support_prompt, parse_support

ROW = "Lagos State 5,725,116 9,113,605 13,491,800"


def test_numbers_in_finds_every_figure_in_a_table_row():
    assert numbers_in(ROW) == [5725116.0, 9113605.0, 13491800.0]


def test_scale_words_are_applied():
    assert numbers_in("about 21 million residents") == [21_000_000.0]


def test_a_figure_present_in_the_quote_is_grounded():
    """
    A whole table row can stand as the quote for one of its cells, which is
    what a model naturally returns when the answer sits in a table.
    """
    assert answer_grounded_in_quote("13,491,800", ROW)


def test_a_figure_absent_from_the_quote_is_not_grounded():
    """
    The layer that catches a genuine quotation paired with a made-up
    number. The row is real; 99,999,999 is not in it.
    """
    assert not answer_grounded_in_quote("99,999,999", ROW)


def test_a_differently_formatted_figure_is_still_grounded():
    assert answer_grounded_in_quote("13491800", ROW)


def test_prose_answers_are_not_blocked_by_this_layer():
    """
    Deliberate. Prose cannot be located numerically, so this defers and the
    support check decides instead of failing an honest answer.
    """
    assert answer_grounded_in_quote("the population is disputed", ROW)


def test_no_quote_means_this_layer_defers():
    assert answer_grounded_in_quote("13,491,800", "")


def test_a_silence_is_always_grounded():
    assert answer_grounded_in_quote("", ROW)


# --------------------------------------------------------------------
# layer three: does the passage answer the question asked
# --------------------------------------------------------------------

def test_the_support_prompt_is_far_smaller_than_a_full_extraction():
    """
    The reason this design works at all. Re-reading the document per
    validator is what made checks time out; asking about one passage is a
    fraction of the payload and a much easier question.
    """
    from contracts.judgment import build_extraction_prompt

    document = "filler. " * 900
    big = build_extraction_prompt("What is the population of Lagos?", document)
    small = build_support_prompt(
        "What is the population of Lagos?", ROW, "13,491,800"
    )
    assert len(small) < len(big) / 5


def test_the_support_prompt_names_the_failure_it_is_looking_for():
    text = build_support_prompt("What is the population?", ROW, "5,725,116")
    assert "historical value where the question asks for a current one" in text
    assert ROW in text


def test_support_is_parsed_from_either_shape():
    assert parse_support({"supports": True})
    assert parse_support('{"supports": true}')
    assert parse_support({"supports": "true"})


def test_a_refusal_is_parsed_as_unsupported():
    assert not parse_support({"supports": False})
    assert not parse_support('{"supports": false}')


def test_unreadable_output_is_treated_as_unsupported():
    """
    The opposite of parse_extraction's rule, deliberately. Reading a broken
    response as approval would wave through the exact thing this check
    exists to stop.
    """
    assert not parse_support("not json at all")
    assert not parse_support(None)
    assert not parse_support({})


# --------------------------------------------------------------------
# the third gap: a claimed silence must not be attestable by a quote
# --------------------------------------------------------------------


def test_an_empty_answer_defers_rather_than_grounding():
    """
    Why a claimed silence can never take the cheap attestation path.

    Layer two asks whether the reported figure sits inside the quotation.
    With no figure reported there is nothing to locate, so it defers and
    answers True. Layer three does not run at all without an answer. So a
    leader attaching a real quotation while reporting nothing would clear
    both, and the validator would then copy the leader's status: a source
    that contradicted the others gets stored as silent, and contested
    becomes corroborated.

    The full re-read is what actually catches it, which is why a claimed
    silence is routed there instead.
    """
    quote = "Nigeria had a population of 195,874,740 in 2018."
    assert answer_grounded_in_quote("", quote) is True
    assert classify("s", "").kind == KIND_ABSTAIN
    # And the check that does catch it.
    assert answers_attest("", "195874740") is False


def test_same_publisher_catches_a_host_sitting_under_another():
    assert same_publisher("example.com", "example.com")
    assert same_publisher("news.example.com", "example.com")
    assert same_publisher("example.com", "news.example.com")


def test_same_publisher_keeps_unrelated_hosts_apart():
    assert not same_publisher("api.worldbank.org", "countriesnow.space")
    # The naive registrable-domain guess would collapse these into one.
    assert not same_publisher("bbc.co.uk", "guardian.co.uk")
    # A shared ending that is not a label boundary is not a parent.
    assert not same_publisher("notexample.com", "example.com")

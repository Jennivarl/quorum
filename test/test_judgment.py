"""
Unit tests for the model layer (contracts/judgment.py).

The isolation test is the one that protects the product's premise. If
extraction prompts can see each other's sources, the oracle reports
agreement the sources do not contain, and every number it produces is
suspect.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contracts.judgment import (
    ANSWER_FOUND,
    ANSWER_NOT_STATED,
    ANSWER_UNREADABLE,
    build_extraction_prompt,
    build_reconciliation_prompt,
    parse_extraction,
    parse_reconciliation,
)

CLAIM = "What was the reported Q1 revenue?"


def test_extraction_prompt_contains_only_the_one_document():
    """
    The premise of corroboration is that sources are read independently.
    A prompt that leaks another source lets a confident document colour
    the reading of an ambiguous one, which fabricates agreement.
    """
    prompt = build_extraction_prompt(CLAIM, "Revenue was 40 million.")
    assert "40 million" in prompt
    assert "other" in prompt.lower()  # it is told others exist but not shown
    assert "Revenue was 12 million" not in prompt


def test_extraction_prompt_tells_the_model_not_to_guess():
    prompt = build_extraction_prompt(CLAIM, "unrelated text")
    assert "rather than inferring" in prompt


def test_long_documents_are_truncated_visibly():
    """
    A silently truncated prompt produces an answer drawn from half a page
    with no indication that happened.
    """
    prompt = build_extraction_prompt(CLAIM, "x" * 9000, max_chars=100)
    assert "[document truncated]" in prompt


def test_parses_a_found_answer():
    got = parse_extraction({"status": "found", "answer": "40 million", "quote": "Revenue was 40 million."})
    assert got.status == ANSWER_FOUND
    assert got.answer == "40 million"


def test_found_with_an_empty_answer_is_not_a_finding():
    got = parse_extraction({"status": "found", "answer": "  "})
    assert got.status == ANSWER_NOT_STATED
    assert got.answer == ""


def test_not_stated_is_preserved():
    assert parse_extraction({"status": "not_stated"}).status == ANSWER_NOT_STATED


def test_unknown_status_becomes_unreadable():
    assert parse_extraction({"status": "probably", "answer": "40"}).status == ANSWER_UNREADABLE


def test_broken_json_becomes_unreadable_not_an_answer():
    """
    Inventing a data point from broken output would put a fabricated
    source into the corroboration count.
    """
    got = parse_extraction("I could not read that document, sorry")
    assert got.status == ANSWER_UNREADABLE
    assert got.answer == ""


def test_markdown_fenced_json_still_parses():
    got = parse_extraction('```json\n{"status":"found","answer":"40m"}\n```')
    assert got.status == ANSWER_FOUND
    assert got.answer == "40m"


def test_reconciliation_splits_agreeing_and_dissenting():
    got = parse_reconciliation({"consensus": "about 40m", "agreeing": [1, 2], "dissenting": [3]}, 3)
    assert got.agreeing == [0, 1]
    assert got.dissenting == [2]
    assert got.consensus == "about 40m"


def test_out_of_range_indices_are_dropped():
    got = parse_reconciliation({"agreeing": [1, 9, 0], "dissenting": []}, 2)
    assert got.agreeing == [0]


def test_unaccounted_answers_are_treated_as_dissent():
    """
    Silence from the reconciler is not evidence of agreement. An answer it
    forgot to mention must not be counted as corroborating.
    """
    got = parse_reconciliation({"agreeing": [1], "dissenting": []}, 3)
    assert got.agreeing == [0]
    assert got.dissenting == [1, 2]


def test_an_answer_cannot_be_in_both_lists():
    got = parse_reconciliation({"agreeing": [1], "dissenting": [1]}, 2)
    assert got.agreeing == [0]
    assert 0 not in got.dissenting


def test_broken_reconciliation_means_nobody_agrees():
    got = parse_reconciliation("not json", 3)
    assert got.agreeing == []
    assert got.dissenting == [0, 1, 2]


def test_reconciliation_prompt_numbers_every_answer():
    prompt = build_reconciliation_prompt(CLAIM, ["rose sharply", "fell slightly"])
    assert "Answer 1: rose sharply" in prompt
    assert "Answer 2: fell slightly" in prompt
